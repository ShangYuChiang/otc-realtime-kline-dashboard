import time
import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from datetime import datetime, timedelta, time as dtime

st.set_page_config(page_title="OTC 櫃買指數", layout="wide")


REALTIME_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
REALTIME_SYMBOL = "otc_o00.tw"
DAILY_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_index"

st.title("OTC 櫃買指數看盤介面")

tab1, tab2 = st.tabs(["歷史日K", "即時分K"])

if "ticks" not in st.session_state:
    st.session_state.ticks = []


@st.cache_data(ttl=600)
def fetch_daily_otc():
    r = requests.get(DAILY_URL, timeout=10)
    r.raise_for_status()
    data = r.json()

    df = pd.DataFrame(data)

    date_col = [c for c in df.columns if "Date" in c or "日期" in c][0]
    close_col = [c for c in df.columns if "Close" in c or "收盤" in c][0]

    df = df[[date_col, close_col]].copy()
    df.columns = ["date", "close"]

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["close"] = (
        df["close"].astype(str)
        .str.replace(",", "", regex=False)
        .astype(float)
    )

    df = df.dropna().sort_values("date")

    df["open"] = df["close"].shift(1).fillna(df["close"])
    df["high"] = df[["open", "close"]].max(axis=1)
    df["low"] = df[["open", "close"]].min(axis=1)
    df["volume"] = 0

    return df.set_index("date")[["open", "high", "low", "close", "volume"]]


def fetch_realtime_otc():
    params = {
        "ex_ch": REALTIME_SYMBOL,
        "json": "1",
        "delay": "0",
        "_": int(time.time() * 1000),
    }

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://mis.twse.com.tw/stock/index.jsp",
    }

    r = requests.get(REALTIME_URL, params=params, headers=headers, timeout=10)
    r.raise_for_status()

    data = r.json()
    arr = data.get("msgArray", [])

    if not arr:
        return None

    item = arr[0]
    price = item.get("z")

    if price in ["-", "", None]:
        return None

    dt = datetime.strptime(item["d"] + " " + item["t"], "%Y%m%d %H:%M:%S")
    price = float(price)

    return {
        "datetime": dt,
        "price": price,
        "volume": float(item.get("v", 0) or 0),
    }


def build_intraday_kbar(ticks, minutes, start_time, end_time):
    df = pd.DataFrame(ticks)

    if df.empty:
        return pd.DataFrame()

    df = df.drop_duplicates("datetime")
    df = df.set_index("datetime").sort_index()

    df = df[
        (df.index.time >= start_time) &
        (df.index.time <= end_time)
    ]

    if df.empty:
        return pd.DataFrame()

    k = df["price"].resample(f"{minutes}min").ohlc()
    k["volume"] = df["volume"].resample(f"{minutes}min").last().diff().fillna(0)

    return k.dropna()

def calc_box_stats(df, box_start, box_end):
    """
    根據使用者指定的時間區間，計算區間內最高、最低，
    並切成四等分，回傳 1/4、2/4、3/4 三條線的位置。
    """
    if box_start is None or box_end is None or df.empty:
        return None

    box_start = pd.to_datetime(box_start)
    box_end = pd.to_datetime(box_end)

    if box_start > box_end:
        box_start, box_end = box_end, box_start

    selected = df[(df.index >= box_start) & (df.index <= box_end)]

    if selected.empty:
        return None

    box_high = float(selected["high"].max())
    box_low = float(selected["low"].min())
    step = (box_high - box_low) / 4

    return {
        "start": box_start,
        "end": box_end,
        "high": box_high,
        "low": box_low,
        "q1": box_low + step,
        "q2": box_low + step * 2,
        "q3": box_low + step * 3,
    }

def draw_chart(
    df,
    title,
    show_first_k_lines=True,
    show_box=False,
    box_start=None,
    box_end=None,
):
    """
    繪製 OTC K 線圖：
    1. 深色背景。
    2. 第一根 K 棒最高點、最低點畫水平綠線。
    3. 指定矩形區間後，抓出區間最高低，畫出矩形，並用三條水平線切成四等分。
    """
    fig = go.Figure()

    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
        increasing_line_color="red",
        decreasing_line_color="white",
        increasing_fillcolor="red",
        decreasing_fillcolor="white",
        name="OTC"
    ))

    fig.add_trace(go.Scatter(
        x=df.index,
        y=df["close"].rolling(20).mean(),
        mode="lines",
        name="MA20",
        line=dict(width=1.5)
    ))

    # 第一根 K 棒最高、最低水平線
    if show_first_k_lines and not df.empty:
        first_high = float(df.iloc[0]["high"])
        first_low = float(df.iloc[0]["low"])

        fig.add_hline(
            y=first_high,
            line_color="lime",
            line_dash="dash",
            line_width=1.5,
            annotation_text=f"第一根高 {first_high:.2f}",
            annotation_position="top left",
            annotation_font_color="lime",
        )

        fig.add_hline(
            y=first_low,
            line_color="lime",
            line_dash="dash",
            line_width=1.5,
            annotation_text=f"第一根低 {first_low:.2f}",
            annotation_position="bottom left",
            annotation_font_color="lime",
        )

    # 矩形區間與四等分線
    box_stats = calc_box_stats(df, box_start, box_end) if show_box else None

    if box_stats:
        x0 = box_stats["start"]
        x1 = box_stats["end"]
        y0 = box_stats["low"]
        y1 = box_stats["high"]

        # 畫矩形框
        fig.add_shape(
            type="rect",
            x0=x0,
            x1=x1,
            y0=y0,
            y1=y1,
            line=dict(color="lime", width=1.5),
            fillcolor="rgba(0, 255, 0, 0.08)",
            layer="below",
        )

        # 三條四等分線
        for label, level in [
            ("1/4", box_stats["q1"]),
            ("2/4", box_stats["q2"]),
            ("3/4", box_stats["q3"]),
        ]:
            fig.add_shape(
                type="line",
                x0=x0,
                x1=x1,
                y0=level,
                y1=level,
                line=dict(color="lime", width=1, dash="dot"),
            )

            fig.add_annotation(
                x=x1,
                y=level,
                text=f"{label}｜{level:.2f}",
                showarrow=False,
                xanchor="left",
                font=dict(color="lime", size=11),
                bgcolor="rgba(0,0,0,0.45)",
            )

        fig.add_annotation(
            x=x1,
            y=y1,
            text=f"區間高 {y1:.2f}",
            showarrow=False,
            xanchor="left",
            font=dict(color="lime", size=11),
            bgcolor="rgba(0,0,0,0.45)",
        )

        fig.add_annotation(
            x=x1,
            y=y0,
            text=f"區間低 {y0:.2f}",
            showarrow=False,
            xanchor="left",
            font=dict(color="lime", size=11),
            bgcolor="rgba(0,0,0,0.45)",
        )

    x_min = df.index.min()
    x_max = df.index.max()
    # 避免只有一根 K 棒時，X 軸被壓成秒級或毫秒級
    if (x_max - x_min) < pd.Timedelta(minutes=1):
        x_max = x_min + pd.Timedelta(minutes=1)

    # X 軸最小刻度為 1 分鐘，但依照資料長度自動放大
    span_minutes = (x_max - x_min).total_seconds() / 60

    if span_minutes <= 10:
        x_dtick = 1 * 60 * 1000       # 1 分鐘
        x_tickformat = "%H:%M"
    elif span_minutes <= 30:
        x_dtick = 5 * 60 * 1000       # 5 分鐘
        x_tickformat = "%H:%M"
    elif span_minutes <= 90:
        x_dtick = 10 * 60 * 1000      # 10 分鐘
        x_tickformat = "%H:%M"
    elif span_minutes <= 240:
        x_dtick = 15 * 60 * 1000      # 15 分鐘
        x_tickformat = "%H:%M"
    elif span_minutes <= 390:
        x_dtick = 30 * 60 * 1000      # 30 分鐘
        x_tickformat = "%H:%M"
    elif span_minutes <= 1440:
        x_dtick = 60 * 60 * 1000      # 1 小時
        x_tickformat = "%H:%M"
    else:
        x_dtick = None                # 歷史日K交給 Plotly 自動
        x_tickformat = "%m/%d"
    y_min = float(df["low"].min())
    y_max = float(df["high"].max())

    y_padding = (y_max - y_min) * 0.03
    if y_padding == 0:
        y_padding = max(abs(y_max) * 0.001, 1)

    fig.update_layout(
        template="plotly_dark",
        height=700,

        title=dict(
            text=title,
            font=dict(
                size=28,          # 標題字體大小
                color="#E5E7EB"
            ),
            x=0.01,
            xanchor="left"
        ),

        # 科技深灰背景
        paper_bgcolor="#111827",
        plot_bgcolor="#111827",
        font=dict(
            color="#E5E7EB",
            size=16              # 全域基本字體
        ),

        xaxis_rangeslider_visible=False,
        yaxis_title="指數",
        hovermode="x unified",
        dragmode="pan",
        margin=dict(l=70, r=100, t=80, b=70),

        legend=dict(
            bgcolor="rgba(17, 24, 39, 0.65)",
            bordercolor="rgba(148, 163, 184, 0.25)",
            borderwidth=1,
            font=dict(
                color="#E5E7EB",
                size=14
            ),
        ),
    )

    fig.update_xaxes(
        range=[x_min, x_max],
        fixedrange=False,

        # X 軸最小刻度 1 分鐘，但不固定死
        dtick=x_dtick,
        tickformat=x_tickformat,
        hoverformat="%Y-%m-%d %H:%M:%S",

        # X 軸字體
        tickfont=dict(
            color="#CBD5E1",
            size=15
        ),
        title_font=dict(
            color="#E5E7EB",
            size=18
        ),

        gridcolor="rgba(148, 163, 184, 0.18)",
        zerolinecolor="rgba(148, 163, 184, 0.28)",
    )

    fig.update_yaxes(
        range=[y_min - y_padding, y_max + y_padding],
        fixedrange=False,

        # Y 軸標題與刻度字體
        title_font=dict(
            color="#E5E7EB",
            size=20
        ),
        tickfont=dict(
            color="#CBD5E1",
            size=16
        ),

        gridcolor="rgba(148, 163, 184, 0.18)",
        zerolinecolor="rgba(148, 163, 184, 0.28)",
    )
    return fig, box_stats


with tab1:
    st.subheader("歷史日K")

    today = datetime.today().date()
    default_start = today - timedelta(days=30)

    c1, c2, c3 = st.columns([1, 1, 1])

    with c1:
        start_date = st.date_input("開始日期", default_start, key="hist_start")

    with c2:
        end_date = st.date_input("結束日期", today, key="hist_end")

    with c3:
        reload_history = st.button("重新抓歷史資料")

    if reload_history:
        st.cache_data.clear()

    try:
        hist_df = fetch_daily_otc()
        hist_df = hist_df[
            (hist_df.index.date >= start_date) &
            (hist_df.index.date <= end_date)
        ]

        if hist_df.empty:
            st.warning("歷史資料為空，請調整日期範圍。")
        else:
            latest = hist_df.iloc[-1]
            first = hist_df.iloc[0]

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("最新收盤", f"{latest['close']:.2f}")
            m2.metric("區間漲跌", f"{latest['close'] - first['open']:.2f}")
            m3.metric("區間最高", f"{hist_df['high'].max():.2f}")
            m4.metric("區間最低", f"{hist_df['low'].min():.2f}")
            st.toggle("顯示矩形四等分", value=False)

            # st.plotly_chart(
            #     draw_chart(hist_df, "OTC 櫃買指數｜歷史日K"),
            #     width='stretch'
            # )
            st.markdown("#### 矩形區間設定")

            h1, h2, h3 = st.columns([1, 1, 1])

            with h1:
                hist_show_box = st.checkbox("顯示歷史矩形四等分", value=False)

            with h2:
                hist_box_start = st.date_input(
                    "矩形開始日期",
                    hist_df.index.min().date(),
                    key="hist_box_start"
                )

            with h3:
                hist_box_end = st.date_input(
                    "矩形結束日期",
                    hist_df.index.max().date(),
                    key="hist_box_end"
                )

            hist_box_start_dt = pd.Timestamp(hist_box_start)
            hist_box_end_dt = pd.Timestamp(hist_box_end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

            fig, box_stats = draw_chart(
                hist_df,
                "OTC 櫃買指數｜歷史日K",
                show_first_k_lines=True,
                show_box=hist_show_box,
                box_start=hist_box_start_dt,
                box_end=hist_box_end_dt,
            )

            if box_stats:
                st.info(
                    f"矩形區間：{box_stats['start'].date()} ~ {box_stats['end'].date()}｜"
                    f"最高 {box_stats['high']:.2f}｜最低 {box_stats['low']:.2f}｜"
                    f"1/4 {box_stats['q1']:.2f}｜2/4 {box_stats['q2']:.2f}｜3/4 {box_stats['q3']:.2f}"
                )
            elif hist_show_box:
                st.warning("矩形區間內沒有資料，請調整日期。")

            st.plotly_chart(fig, width='stretch')
            st.dataframe(hist_df.tail(50))

    except Exception as e:
        st.error(f"歷史資料抓取失敗：{e}")


with tab2:
    st.subheader("即時分K")

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        bar_minutes = st.selectbox(
            "分K週期",
            [1, 2, 3, 5, 10, 15, 30],
            index=1
        )

    with c2:
        start_time = st.time_input("開始時間", dtime(9, 0))

    with c3:
        end_time = st.time_input("結束時間", dtime(13, 30))

    with c4:
        refresh_seconds = st.slider("更新秒數", 5, 60, 30)

    c5, c6 = st.columns([1, 1])

    with c5:
        auto_refresh = st.toggle("開始即時更新", value=True)

    with c6:
        if st.button("清空即時資料"):
            st.session_state.ticks = []
            st.rerun()

    try:
        if auto_refresh:
            q = fetch_realtime_otc()
            if q:
                st.session_state.ticks.append(q)

        kbar_df = build_intraday_kbar(
            st.session_state.ticks,
            bar_minutes,
            start_time,
            end_time
        )

        if kbar_df.empty:
            st.warning("即時分K尚未累積資料。交易時間開著程式後會開始累積。")
        else:
            # Save the intraday K-bar data to a CSV file before plotting.
            # The filename follows the pattern "OTC_YYYYMMDD.csv" using
            # today's date in the Asia/Taipei timezone. This allows the
            # accumulated intraday data to be persisted for later review.
            save_date = datetime.now().strftime("%Y%m%d")
            filename = f"OTC_{save_date}.csv"
            try:
                kbar_df.to_csv(filename)
                # Notify the user that the file has been saved.
                st.success(f"即時分K資料已儲存為 {filename}")
            except Exception as save_err:
                # If saving fails, warn the user but continue with plotting.
                st.warning(f"儲存即時資料失敗：{save_err}")

            latest = kbar_df.iloc[-1]
            first = kbar_df.iloc[0]

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("最新指數", f"{latest['close']:.2f}")
            m2.metric("區間漲跌", f"{latest['close'] - first['open']:.2f}")
            m3.metric("區間最高", f"{kbar_df['high'].max():.2f}")
            m4.metric("區間最低", f"{kbar_df['low'].min():.2f}")

            # st.plotly_chart(
            #     draw_chart(kbar_df, f"OTC 櫃買指數｜即時 {bar_minutes} 分K"),
            #     use_container_width=True
            # )
            st.markdown("#### 矩形區間設定")

            intra_show_box = st.toggle(
                "開啟即時矩形四等分",
                value=False,
                key="intra_show_box"
            )

            intra_box_start_dt = None
            intra_box_end_dt = None

            if intra_show_box:
                i1, i2 = st.columns(2)

                with i1:
                    intra_box_start_time = st.time_input(
                        "矩形開始時間",
                        kbar_df.index.min().time(),
                        key="intra_box_start_time"
                    )

                with i2:
                    intra_box_end_time = st.time_input(
                        "矩形結束時間",
                        kbar_df.index.max().time(),
                        key="intra_box_end_time"
                    )

                trade_date = kbar_df.index.max().date()

                intra_box_start_dt = datetime.combine(
                    trade_date,
                    intra_box_start_time
                )

                intra_box_end_dt = datetime.combine(
                    trade_date,
                    intra_box_end_time
                )

            fig, box_stats = draw_chart(
                kbar_df,
                f"OTC 櫃買指數｜即時 {bar_minutes} 分K",
                show_first_k_lines=True,
                show_box=intra_show_box,
                box_start=intra_box_start_dt,
                box_end=intra_box_end_dt,
            )

            if intra_show_box:
                if box_stats:
                    st.info(
                        f"矩形區間：{box_stats['start'].time()} ~ {box_stats['end'].time()}｜"
                        f"最高 {box_stats['high']:.2f}｜最低 {box_stats['low']:.2f}｜"
                        f"1/4 {box_stats['q1']:.2f}｜"
                        f"2/4 {box_stats['q2']:.2f}｜"
                        f"3/4 {box_stats['q3']:.2f}"
                    )
                else:
                    st.warning("矩形區間內沒有資料，請調整時間。")

            st.plotly_chart(fig, width='stretch')

            st.dataframe(kbar_df.tail(50))

        if auto_refresh:
            time.sleep(refresh_seconds)
            st.rerun()

    except Exception as e:
        st.error(f"即時資料抓取失敗：{e}")