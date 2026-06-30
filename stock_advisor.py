"""
株情報取得モジュール - ハルの投資サポート機能
"""

import yfinance as yf

WATCH_LIST = [
    ("^N225",   "日経225"),
    ("1802.T",  "大林組"),
    ("1803.T",  "清水建設"),
    ("8801.T",  "三井不動産"),
    ("7203.T",  "トヨタ"),
    ("6758.T",  "ソニーG"),
    ("4063.T",  "信越化学"),
    ("8306.T",  "三菱UFJ"),
]

STOCK_KEYWORDS = [
    "株", "銘柄", "投資", "日経", "NISA", "ニーサ", "配当",
    "買い", "売り", "上昇", "下落", "ポートフォリオ", "相場",
    "証券", "ETF", "資産運用",
]


def is_stock_query(message: str) -> bool:
    return any(kw in message for kw in STOCK_KEYWORDS)


def build_market_context() -> str:
    tickers = [t for t, _ in WATCH_LIST]
    names = {t: n for t, n in WATCH_LIST}

    try:
        data = yf.download(tickers, period="5d", progress=False, auto_adjust=True)
        closes = data["Close"]

        rows = []
        for ticker in tickers:
            if ticker not in closes.columns:
                continue
            series = closes[ticker].dropna()
            if series.empty:
                continue
            latest = float(series.iloc[-1])
            prev = float(series.iloc[-2]) if len(series) >= 2 else latest
            change = latest - prev
            pct = change / prev * 100 if prev else 0
            arrow = "▲" if change >= 0 else "▼"
            sign = "+" if change >= 0 else ""
            rows.append(
                f"{names[ticker]}: {latest:,.0f}  {arrow}{sign}{pct:.2f}%"
            )

        if not rows:
            return (
                "【市場データを取得できませんでした】\n"
                "お手数ですが証券会社サイトで最新情報をご確認ください。"
            )

        lines = ["【本日の株式市場データ】"] + rows + [
            "\n※上記データを参考に、社長の長期資産形成・配当重視の方針で"
            "スマホで読みやすい形でアドバイスしてください。"
            "最終判断は社長ご自身でと必ず添えること。"
        ]
        return "\n".join(lines)

    except Exception:
        return (
            "【市場データを取得できませんでした】\n"
            "お手数ですが証券会社サイトで最新情報をご確認ください。"
        )
