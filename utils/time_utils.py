from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Tuple

def now_with_unix(tz: str) -> Tuple[datetime, int]:
    """
    回傳當前時區時間與 Unix timestamp。
    """
    now = datetime.now(ZoneInfo(tz))
    return now, int(now.timestamp())