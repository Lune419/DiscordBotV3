import re
import json
from typing import Dict
from datetime import datetime
from zoneinfo import ZoneInfo

with open("config.json", "r", encoding="utf-8") as fp:
    cfg = json.load(fp)


def parse_time_string(time_str: str) -> int:
    """
    將時間字符串轉換為秒數。
    
    格式: 
    - Y: 年 (365天)
    - M: 月 (30天)
    - D: 天
    - H: 小時
    - m: 分鐘
    - s: 秒
    
    例如:
    - "1Y2M3D4H5m6s" = 1年2月3天4小時5分6秒
    - "5m30s" = 5分鐘30秒
    - "1D" = 1天
    
    Args:
        time_str: 符合格式的時間字符串
    
    Returns:
        轉換後的秒數
    
    Raises:
        ValueError: 如果格式無效
    """
    if not time_str:
        return 0
        
    # 時間單位與其對應的秒數
    time_units: Dict[str, int] = {
        'Y': 365 * 24 * 60 * 60,  # 年 (以365天計算)
        'M': 30 * 24 * 60 * 60,   # 月 (以30天計算)
        'D': 24 * 60 * 60,        # 天
        'H': 60 * 60,             # 小時
        'm': 60,                  # 分鐘
        's': 1                    # 秒
    }
    
    # 使用正則表達式找出所有時間片段
    pattern = r'(\d+)([YMDHms])'
    matches = re.findall(pattern, time_str)
    
    if not matches:
        raise ValueError(f"無效的時間格式: {time_str}")
    
    total_seconds = 0
    
    # 計算總秒數
    for value, unit in matches:
        try:
            value_int = int(value)
            if value_int < 0:
                raise ValueError(f"時間值不能為負數: {value}{unit}")
                
            if unit in time_units:
                total_seconds += value_int * time_units[unit]
            else:
                raise ValueError(f"未知的時間單位: {unit}")
        except ValueError as e:
            if "invalid literal for int" in str(e):
                raise ValueError(f"無效的時間值: {value}")
            raise
    
    return total_seconds

def format_seconds(seconds: int) -> str:
    """
    將秒數轉換為人類可讀的時間格式。
    
    Args:
        seconds: 要轉換的秒數
    
    Returns:
        格式化的時間字符串，例如 "1Y2M3D4H5m6s"
    """
    if seconds < 0:
        raise ValueError("秒數不能為負數")
        
    # 時間單位與其對應的秒數
    time_units = [
        ('Y', 365 * 24 * 60 * 60),
        ('M', 30 * 24 * 60 * 60),
        ('D', 24 * 60 * 60),
        ('H', 60 * 60),
        ('m', 60),
        ('s', 1)
    ]
    
    if seconds == 0:
        return "0s"
    
    result = []
    remaining = seconds
    
    for unit, unit_seconds in time_units:
        if remaining >= unit_seconds:
            value = remaining // unit_seconds
            remaining %= unit_seconds
            result.append(f"{value}{unit}")
    
    return "".join(result)



def date_format(unix_time):
    """ 將unix時間轉為 Y-m-d H:M:S 的形式 """
    return datetime.fromtimestamp(unix_time, ZoneInfo(cfg["timezone"])).strftime("%Y-%m-%d %H:%M:%S")