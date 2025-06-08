本文檔由https://github.com/welkineins/tw-google-styleguide.git中節錄



註釋
--------------------

tip:
    確保對模塊, 函數, 方法和行內註釋使用正確的風格

**文檔字符串**

    Python有一種獨一無二的的註釋方式: 使用文檔字符串. 文檔字符串是包, 模塊, 類或函數里的第一個語句. 這些字符串可以通過對象的__doc__成員被自動提取, 並且被pydoc所用. (你可以在你的模塊上運行pydoc試一把, 看看它長什麼樣). 我們對文檔字符串的慣例是使用三重雙引號"""( `PEP-257 <http://www.python.org/dev/peps/pep-0257/>`_ ). 一個文檔字符串應該這樣組織: 首先是一行以句號, 問號或驚歎號結尾的概述(或者該文檔字符串單純只有一行). 接著是一個空行. 接著是文檔字符串剩下的部分, 它應該與文檔字符串的第一行的第一個引號對齊. 下面有更多文檔字符串的格式化規範.

**模塊**

    每個文件應該包含一個許可樣板. 根據項目使用的許可(例如, Apache 2.0, BSD, LGPL, GPL), 選擇合適的樣板.

**函數和方法**

    下文所指的函數,包括函數, 方法, 以及生成器.

    一個函數必須要有文檔字符串, 除非它滿足以下條件:

    #. 外部不可見
    #. 非常短小
    #. 簡單明瞭

    文檔字符串應該包含函數做什麼, 以及輸入和輸出的詳細描述. 通常, 不應該描述"怎麼做", 除非是一些複雜的算法. 文檔字符串應該提供足夠的信息, 當別人編寫代碼調用該函數時, 他不需要看一行代碼, 只要看文檔字符串就可以了. 對於複雜的代碼, 在代碼旁邊加註釋會比使用文檔字符串更有意義.

    關於函數的幾個方面應該在特定的小節中進行描述記錄， 這幾個方面如下文所述. 每節應該以一個標題行開始. 標題行以冒號結尾. 除標題行外, 節的其他內容應被縮進2個空格.

    Args:
        列出每個參數的名字, 並在名字後使用一個冒號和一個空格, 分隔對該參數的描述.如果描述太長超過了單行80字符,使用2或者4個空格的懸掛縮進(與文件其他部分保持一致).
        描述應該包括所需的類型和含義.
        如果一個函數接受*foo(可變長度參數列表)或者**bar (任意關鍵字參數), 應該詳細列出*foo和**bar.

    Returns: (或者 Yields: 用於生成器)
        描述返回值的類型和語義. 如果函數返回None, 這一部分可以省略.

    Raises:
        列出與接口有關的所有異常.

    .. code-block:: python

        def fetch_bigtable_rows(big_table, keys, other_silly_variable=None):
            """Fetches rows from a Bigtable.

            Retrieves rows pertaining to the given keys from the Table instance
            represented by big_table.  Silly things may happen if
            other_silly_variable is not None.

            Args:
                big_table: An open Bigtable Table instance.
                keys: A sequence of strings representing the key of each table row
                    to fetch.
                other_silly_variable: Another optional variable, that has a much
                    longer name than the other args, and which does nothing.

            Returns:
                A dict mapping keys to the corresponding table row data
                fetched. Each row is represented as a tuple of strings. For
                example:

                {'Serak': ('Rigel VII', 'Preparer'),
                 'Zim': ('Irk', 'Invader'),
                 'Lrrr': ('Omicron Persei 8', 'Emperor')}

                If a key from the keys argument is missing from the dictionary,
                then that row was not found in the table.

            Raises:
                IOError: An error occurred accessing the bigtable.Table object.
            """
            pass

**類**

    類應該在其定義下有一個用於描述該類的文檔字符串. 如果你的類有公共屬性(Attributes), 那麼文檔中應該有一個屬性(Attributes)段. 並且應該遵守和函數參數相同的格式.

    .. code-block:: python

        class SampleClass(object):
            """Summary of class here.

            Longer class information....
            Longer class information....

            Attributes:
                likes_spam: A boolean indicating if we like SPAM or not.
                eggs: An integer count of the eggs we have laid.
            """

            def __init__(self, likes_spam=False):
                """Inits SampleClass with blah."""
                self.likes_spam = likes_spam
                self.eggs = 0

            def public_method(self):
                """Performs operation blah."""



**塊註釋和行註釋**

    最需要寫註釋的是代碼中那些技巧性的部分. 如果你在下次 `代碼審查 <http://en.wikipedia.org/wiki/Code_review>`_ 的時候必須解釋一下, 那麼你應該現在就給它寫註釋. 對於複雜的操作, 應該在其操作開始前寫上若干行註釋. 對於不是一目瞭然的代碼, 應在其行尾添加註釋.

    .. code-block:: python

        # We use a weighted dictionary search to find out where i is in
        # the array.  We extrapolate position based on the largest num
        # in the array and the array size and then do binary search to
        # get the exact number.

        if i & (i-1) == 0:        # true iff i is a power of 2

    為了提高可讀性, 註釋應該至少離開代碼2個空格.

    另一方面, 絕不要描述代碼. 假設閱讀代碼的人比你更懂Python, 他只是不知道你的代碼要做什麼.

    .. code-block:: python

        # BAD COMMENT: Now go through the b array and make sure whenever i occurs
        # the next element is i+1


類
--------------------

.. tip::
    如果一個類不繼承自其它類, 就顯式的從object繼承. 嵌套類也一樣.

.. code-block:: python

    Yes: class SampleClass(object):
             pass


         class OuterClass(object):

             class InnerClass(object):
                 pass


         class ChildClass(ParentClass):
             """Explicitly inherits from another class already."""

.. code-block:: python

    No: class SampleClass:
            pass


        class OuterClass:

            class InnerClass:
                pass

繼承自 ``object`` 是為了使屬性(properties)正常工作, 並且這樣可以保護你的代碼, 使其不受Python 3000的一個特殊的潛在不兼容性影響. 這樣做也定義了一些特殊的方法, 這些方法實現了對象的默認語義, 包括 ``__new__, __init__, __delattr__, __getattribute__, __setattr__, __hash__, __repr__, and __str__`` .

字符串
--------------------

.. tip::
    即使參數都是字符串, 使用%操作符或者格式化方法格式化字符串. 不過也不能一概而論, 你需要在+和%之間好好判定.

.. code-block:: python

    Yes: x = a + b
         x = '%s, %s!' % (imperative, expletive)
         x = '{}, {}!'.format(imperative, expletive)
         x = 'name: %s; score: %d' % (name, n)
         x = 'name: {}; score: {}'.format(name, n)

.. code-block:: python

    No: x = '%s%s' % (a, b)  # use + in this case
        x = '{}{}'.format(a, b)  # use + in this case
        x = imperative + ', ' + expletive + '!'
        x = 'name: ' + name + '; score: ' + str(n)

避免在循環中用+和+=操作符來累加字符串. 由於字符串是不可變的, 這樣做會創建不必要的臨時對像, 並且導致二次方而不是線性的運行時間. 作為替代方案, 你可以將每個子串加入列表, 然後在循環結束後用 ``.join`` 連接列表. (也可以將每個子串寫入一個 ``cStringIO.StringIO`` 緩存中.)

.. code-block:: python

    Yes: items = ['<table>']
         for last_name, first_name in employee_list:
             items.append('<tr><td>%s, %s</td></tr>' % (last_name, first_name))
         items.append('</table>')
         employee_table = ''.join(items)

.. code-block:: python

    No: employee_table = '<table>'
        for last_name, first_name in employee_list:
            employee_table += '<tr><td>%s, %s</td></tr>' % (last_name, first_name)
        employee_table += '</table>'

在同一個文件中, 保持使用字符串引號的一致性. 使用單引號'或者雙引號"之一用以引用字符串, 並在同一文件中沿用. 在字符串內可以使用另外一種引號, 以避免在字符串中使用\. GPyLint已經加入了這一檢查.

(譯者注:GPyLint疑為筆誤, 應為PyLint.)

.. code-block:: python

   Yes:
        Python('Why are you hiding your eyes?')
        Gollum("I'm scared of lint errors.")
        Narrator('"Good!" thought a happy Python reviewer.')

.. code-block:: python

   No:
        Python("Why are you hiding your eyes?")
        Gollum('The lint. It burns. It burns us.')
        Gollum("Always the great lint. Watching. Watching.")

為多行字符串使用三重雙引號"""而非三重單引號'''. 當且僅當項目中使用單引號'來引用字符串時, 才可能會使用三重'''為非文檔字符串的多行字符串來標識引用. 文檔字符串必須使用三重雙引號""". 不過要注意, 通常用隱式行連接更清晰, 因為多行字符串與程序其他部分的縮進方式不一致.

.. code-block:: python

    Yes:
        print ("This is much nicer.\n"
               "Do it this way.\n")

.. code-block:: python

    No:
          print """This is pretty ugly.
      Don't do this.
      """