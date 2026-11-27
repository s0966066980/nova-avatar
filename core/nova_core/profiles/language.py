# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Conversation-language copies of fixed replies, never topic routing."""


_ENGLISH = {
    '目前角色正在轉場，請稍候': 'The avatar is transitioning. Please wait.',
    '目前無法確認問題的接手方式，請再說一次您的問題。': 'I could not determine which role should help. Please ask your question again.',
    '請問您想先詢問哪個主題？': 'Which topic would you like to ask about?',
    '請問您想查詢哪個縣市的天氣？': 'Which city or county would you like the weather for?',
    '請問您想查詢臺灣哪個縣市及鄉鎮？': 'Which city or county and district in Taiwan would you like to ask about?',
    '請問您想查詢哪個縣市及鄉鎮的天氣？': 'Which city or county and district would you like the weather for?',
    '目前提供未來七天的天氣預報，請指定這個範圍內的日期。': 'Forecasts are available for the next seven days. Please choose a date within that range.',
    '目前暫時無法取得所問的最新天氣資料，請稍後再試。': 'The latest weather data is temporarily unavailable. Please try again later.',
}


def fixed_text(text, locale):
    return _ENGLISH.get(text, text) if locale == 'en-US' else text

