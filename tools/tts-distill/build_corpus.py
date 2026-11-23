#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Build a phonetically diverse zh-TW + en-US distillation corpus for Nova Avatar."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

_ZH_GREETINGS = [
    "您好，歡迎來到 Nova Avatar 展示現場，請問今天需要什麼協助？",
    "早安，很高興為您服務，請隨時告訴我您的需求或問題。",
    "午安，需要幫您查詢今天的行程、天氣預報或知識庫資料嗎？",
    "晚安，請問還有哪裡需要補充說明或再次確認的嗎？",
    "沒問題，我馬上幫您查詢最新資訊，請稍候幾秒鐘。",
    "好的，我已經幫您整理好重點，現在逐項為您說明。",
    "不好意思讓您久等了，我們接著討論剛才提到的細節。",
    "這個功能主要設計給展場互動、客服導覽與即時語音問答使用。",
    "如果您想切換成英文模式，也可以直接用英語對我發問。",
    "系統目前運作穩定，語音合成與嘴型畫面都保持同步。",
]

# Diverse Taiwanese cities, transit, weather, and daily vocabulary crafted to
# cover broad Mandarin initials, finals, and all five lexical tones.
_TAIWAN_CITIES_WEATHER = (
    ("台北市信義區", "晴朗炎熱", "二十八度", "三十五度"),
    ("新北市板橋區", "多雲時晴", "二十四度", "三十一度"),
    ("基隆市仁愛區", "陰天有短暫雨", "二十一度", "二十五度"),
    ("桃園市大園區", "微風陣陣", "二十二度", "二十九度"),
    ("新竹縣竹北市", "風勢偏強", "二十三度", "二十八度"),
    ("苗栗縣頭份市", "舒適涼爽", "二十度", "二十七度"),
    ("台中市西屯區", "晴時多雲", "二十五度", "三十二度"),
    ("彰化縣員林市", "午後雷陣雨", "二十四度", "三十度"),
    ("南投縣埔里鎮", "清晨起霧", "十八度", "二十六度"),
    ("嘉義市東區", "陽光充足", "二十六度", "三十三度"),
    ("台南市安平區", "悶熱潮濕", "二十七度", "三十四度"),
    ("高雄市左營區", "晴空萬里", "二十八度", "三十五度"),
    ("屏東縣恆春鎮", "落山風吹拂", "二十五度", "三十一度"),
    ("宜蘭縣羅東鎮", "細雨綿綿", "十九度", "二十四度"),
    ("花蓮縣壽豐鄉", "雲層偏厚", "二十一度", "二十六度"),
    ("台東縣池上鄉", "微涼乾燥", "二十二度", "二十九度"),
)

_WEATHER_TEMPLATES = (
    "今天{place}天氣{cond}，早晚低溫約{low}，中午最高可達{high}。",
    "氣象署預報指出，{place}週末維持{cond}，氣溫介於{low}到{high}之間。",
    "如果您準備前往{place}旅遊，當地目前{cond}，記得留意{low}至{high}的溫差。",
)

_TRANSIT_SENTENCES = (
    "高鐵左營站下午兩點十五分發車，預計三點四十分抵達台中烏日站。",
    "台北捷運板南線目前班距正常，請從三號出口右轉步行五分鐘。",
    "桃園國際機場第二航廈報到櫃檯位於三樓北側，請提早兩小時辦理登機。",
    "台鐵太魯閣號與普悠瑪號均需事先購買對號車票，無法刷悠遊卡進站。",
    "前往淡水漁人碼頭與九份老街的公車假日容易塞車，建議改搭火車接駁。",
    "高速公路南下路段傍晚車流增加，經過雪山隧道與八卦山時請保持車距。",
    "這班客運沿途停靠林口、中壢、新竹清大與逢甲商圈，全程約三個半小時。",
    "旅客若遺失隨身行李或雨傘，可洽詢各車站服務台登記協尋編號。",
    "停車場地下二樓設有電動車快速充電樁，離場前請先使用自動繳費機。",
    "若遇颱風警報或豪雨特報，輪船與森林鐵路將視安全狀況公告停駛。",
)

# High-diversity Taiwanese Mandarin sentences emphasizing natural sandhi and
# varied contexts around common particles/homophones (的, 對, 得, 地, 是, 在, 了).
_ZH_CONVERSATIONAL_DE_DUI = (
    "你剛才說的重點我都記下來了，這樣安排確實比較穩妥。",
    "對不起，剛才網路訊號有點延遲，麻煩您再說一次您的需求。",
    "這件事對團隊來說很重要，我們應該先聽聽大家的意見。",
    "如果沒有其他問題的話，我們就按照原先的計畫繼續執行。",
    "他對這份報告的內容相當滿意，特別肯定圖表的呈現方式。",
    "把每個步驟交代得清清楚楚，合作起來自然就會更有效率。",
    "這家店的咖啡香醇順口，搭配手工製作的甜點真是絕配。",
    "面對這麼複雜的狀況，冷靜分析問題的根源才是正確的態度。",
    "你的建議很有道理，我覺得把順序對調一下會更流暢。",
    "不管外界的雜音有多少，做好自己該負的責任最重要。",
    "我記得昨天開會的時候，大家對新的時間表已經達成共識。",
    "這套工具的操作介面設計得很直覺，新手也能很快上手。",
    "為了避免後續的誤會，請先把雙方的權利與義務寫清楚。",
    "今天下午的陽光柔和舒適，很適合到公園的步道散步。",
    "他在專業領域累積了多年的經驗，對細節的掌握非常精準。",
    "如果你對這筆訂單有疑問，可以隨時聯絡客服中心的專員。",
    "好的，我完全理解你的考量，明天早上會再寄出更新後的檔案。",
    "這條山路風景優美，只是轉彎處的視線不太好，開車得格外留心。",
    "我們必須對品質維持高標準的要求，才能贏得客戶長久的信任。",
    "你穿這件外套看起來很有精神，顏色跟今天的場合非常相配。",
    "看清楚合約上的條款再簽名，才是保護自己權益的好習慣。",
    "雖然過程遇到不少挑戰，但最後呈現的效果比預期的還要理想。",
    "他的語氣聽起來有點急促，可能真的碰上很緊急的狀況了。",
    "我覺得這兩種做法各有優缺點，端看你現階段最在意哪一項指標。",
    "對了，差點忘記提醒你，下午三點的線上會議已經改到四點開始。",
    "窗外的風勢逐漸變強，看樣子待會兒可能會下起一陣急雨。",
    "謝謝你的體諒與幫忙，讓我能夠在期限之前順利交出作品。",
    "這本書用淺顯易懂的例子，把艱深的理論解釋得相當透徹。",
    "你提到的那個版本我有印象，裡面的結構比舊版精簡了許多。",
    "只要方向是正確的，就算走得慢一點，最終還是能到達終點。",
    "他對待同事總是客氣又耐心，難怪大家都很喜歡跟他共事。",
    "這道料理的火候控制得恰到好處，外皮酥脆而內裡保持鮮嫩。",
    "我的想法跟您差不多，先測試核心流程沒問題，再擴充周邊功能。",
    "在做出最後的決定之前，最好再核對一次所有的原始數據。",
    "聽完他的說明之後，我對整體的架構頓時有了清晰的輪廓。",
    "每天撥出二十分鐘運動，對維持精神與專注力很有幫助。",
    "請問您想要預約哪一天的時段？目前週四上午還有空檔。",
    "這張照片的構圖非常自然，把夕陽映照在海面的光影拍得真美。",
    "別太擔心明天的簡報，你準備得這麼充分，表現一定沒問題的。",
    "有時候換個角度看事情，原本棘手的難題也能找到突破口。",
    "他習慣把每天的待辦事項列在筆記本裡，完成一項就打個勾。",
    "這個方案的成本雖然偏高，但長期帶來的效益相當可觀。",
    "對健康有益的生活習慣，往往需要一點耐心去慢慢培養。",
    "剛出爐的麵包散發出淡淡的小麥香氣，讓人忍不住想多買幾個。",
    "我們需要確認系統在離線的環境下，依然能保持穩定的反應速度。",
    "對於剛加入的新夥伴，前輩們都會安排詳細的環境設定教學。",
    "這首曲子的節奏輕快明亮，很適合當作早晨通勤時的背景音樂。",
    "請幫我確認門窗是否已經關好，確認無誤後我們就出發吧。",
    "他的記性真好，幾年前聊過的小細節到現在還記得一清二楚。",
    "這種雙重驗證的設計，大幅降低了帳號遭到未授權登入的風險。",
    "如果不確定哪條路線比較快，可以先打開即時路況地圖對比看看。",
    "她總是能迅速抓住談話的重點，並用簡潔的語言整理出結論。",
    "面對突如其來的變動，保持彈性的規劃比盲目趕工更為明智。",
    "這台螢幕的色彩還原度極高，非常適合用來進行影像調色工作。",
    "你的態度如此誠懇，相信對方一定能感受到你的滿滿善意。",
    "在這個安靜的午後，泡一杯溫熱的高山茶慢慢閱讀真是享受。",
    "關於這個錯誤訊息的成因，我們還需要比對兩邊的紀錄檔才能確定。",
    "他說得一點也沒錯，事前的預防永遠比事後的補救來得輕鬆。",
    "無論是晴天還是雨天，這座城市都有著截然不同的迷人風景。",
    "今天的主餐風味獨特，可惜配菜的份量稍微少了一點點。",
    "對待每一場對話都保持專注，是讓互動品質更上一層樓的關鍵。",
    "這支麥克風的收音範圍很集中，能有效過濾掉側邊的環境雜音。",
    "既然大家都對修改後的草案沒有異議，那就正式拍板定案吧。",
    "我必須承認剛開始確實有些緊張，但講了幾句之後就自然多了。",
    "把複雜的知識拆解成簡單的步驟，才能讓更多人輕鬆聽得懂。",
    "他們兩家公司的定位完全不同，直接放在一起對比其實不太公平。",
    "記得把重要的文件備份到另一顆硬碟，這樣才算真正安全妥當。",
    "夜晚的微風吹散了白天的悶熱，走在河濱公園感覺十分涼快。",
    "您選的這個座位視野很好，剛好能把整座舞台的動態一覽無遺。",
    "如果遇到無法解決的技術障礙，歡迎隨時把錯誤截圖傳給我分析。",
    "對自己有信心一點，這些年累積的實力不會輕易辜負你的付出。",
    "這套演算法的運算速度雖然快，但對於邊界條件的處理還不夠嚴謹。",
    "趁著週末天氣放晴，不少家庭都帶著孩子來到草地上放風箏。",
    "我覺得偶爾放慢腳步整理思緒，對接下來的創作靈感很有幫助。",
    "這份問卷收集了上千名使用者的回饋，反映出相當真實的市場需求。",
    "請對準鏡頭中央的位置，系統會在三秒鐘後自動完成人臉校正。",
    "他在關鍵時刻總能挺身而出，展現出令人敬佩的冷靜與擔當。",
    "這雙運動鞋的鞋底支撐性很棒，就算走上一整天也不覺得累。",
    "我們已經把相關的權限開通好了，現在您可以直接登入查看結果。",
    "對比去年同期的銷售數字，今年第三季的成長幅度確實非常亮眼。",
    "說話的速度放慢一點、咬字清楚一點，聽眾就能吸收得更完整。",
    "這間圖書館藏書豐富，而且靠窗的閱讀區光線明亮又安靜。",
    "不管任務有多艱鉅，只要團隊分工明確，就一定能順利克服。",
    "你剛剛的提問切中了核心，這正是我們目前最需要解決的盲點。",
    "每天睡前把手機放到遠一點的地方，對改善睡眠品質很有效果。",
    "這種傳統手作工藝需要極大的耐心，幾乎每個步驟都馬虎不得。",
    "既然時間已經有點緊迫了，我們先處理最迫切的幾個項目再說。",
    "他的幽默感總能適時化解緊張的氣氛，讓討論重新回到正軌。",
    "我對這座城市的印象非常好，街道整潔，居民也都很熱情友善。",
    "這份檢核表列出所有需要注意的細節，出門前對照一遍就不怕漏掉。",
    "雖然表面上看起來風平浪靜，但底下的細節其實經過反覆打磨。",
    "當你把注意力集中在真正重要的事情上，效率自然就會跟著提升。",
    "請問剛才那段語音合成的音量大小合適嗎？會不會太尖銳或太小聲？",
    "這座古蹟保存得非常完整，一磚一瓦都訴說著過去百年的歷史記憶。",
    "對客戶提出的要求我們會盡力配合，同時也會說明合理的工期限制。",
    "她說話的語調溫柔堅定，讓人聽了就覺得相當安心與信賴。",
    "今天的工作進度比預想中順利得多，看來傍晚可以準時下班休息了。",
    "把這兩個模組的介面整理得一致一些，後續維護起來會省力很多。",
    "我喜歡在清晨出門慢跑，呼吸新鮮空氣的同時順便規劃一天的行程。",
    "這段測試錄音的清晰度比上一版好了不少，幾乎聽不到多餘的雜訊。",
    "這個答案究竟對不對，還需要等老師公佈解答之後才能確定。",
    "請把單據上的金額跟明細逐筆核對清楚，確認沒有遺漏再送出。",
    "我們公司對外的聯絡窗口已經更新，有需要請直接寄信給專責同事。",
    "這間餐廳就在捷運站斜對面，過個馬路走過去不用兩分鐘就到了。",
    "他的觀點跟我們的立場剛好相反，但這不代表彼此沒有合作的空間。",
    "這兩組藍牙耳機配對的速度非常快，從充電盒拿出來就自動連線了。",
    "今天下午的講座主題是人工智慧與語音合成的應用，歡迎大家踴躍參加。",
    "在沒有百分之百的把握之前，我們絕對不能隨便對外承諾交貨日期。",
    "這些零散的筆記如果能整理成結構清晰的表格，閱讀起來一定輕鬆得多。",
    "我反對為了追求速度而犧牲品質，穩紮穩打才是長久經營的秘訣。",
    "相對來說，這個版本所需要的記憶體容量比較小，很適合邊緣裝置部署。",
    "請幫忙把桌上的文件照著編號排整齊，免得等一下開會找不到要用的那一頁。",
    "他跟對手在決賽中展現出極佳的運動家精神，贏得全場觀眾的熱烈掌聲。",
    "這組數據對應的曲線有點異常，請工程師幫忙檢查感測器的校正紀錄。",
    "雖然她嘴上說沒關係，但從表情還是能感覺得出來她對結果有點失望。",
    "把這兩個段落的順序對調過來，整篇文章的邏輯銜接就會順暢很多。",
    "我們對未來的合作抱持樂觀的態度，也期待看到更多創新的產品問世。",
    "這家書店週末全館書籍打八折，特價區的經典小說甚至對折出售。",
    "面對這麼高的期待與壓力，他選擇用實際的成果來回應各界的質疑。",
    "好的設計不只是外觀漂亮而已，更要考量到使用者日常操作的便利性。",
    "這條規定是針對所有新進成員訂定的，目的是幫助大家更快融入團隊。",
    "你在電話裡提到的那幾個細節我都寫在便條紙上了，等會兒立刻處理。",
    "只要雙方的目標是一致的，溝通上的小摩擦很快就能順利化解。",
    "為了提升對話的流暢度，系統會自動記住前幾輪問答的上下文脈絡。",
    "這件襯衫的剪裁相當合身，布料摸起來也很透氣，很適合台灣的夏天。",
    "請不要忘記每天定時備份重要的工作資料，養成良好的資安防護習慣。",
    "她用流利的外語跟現場來賓熱情交流，展現出十足的自信與專業度。",
    "這條河岸兩旁的自行車道鋪設得很平坦，假日常常能看到親子一起騎車。",
    "對於剛接觸這個領域的朋友來說，從基礎的觀念慢慢學起最為紮實。",
    "這份提案經過三次大幅度的修改，終於獲得主管與客戶的一致認同。",
    "如果發覺聲音聽起來有點乾澀或破音，先把總音量稍微往下調一點看看。",
    "我們需要更精準的測試樣本，才能判斷這個修正是否真的解決了問題。",
    "他在筆記的最後一頁寫下自己的心得，提醒自己永遠保持好奇與謙虛。",
    "這家老字號麵店的湯頭濃郁卻不油膩，每天中午都吸引大批上班族排隊。",
    "請幫我轉告對門的張先生，他訂購的包裹已經送到一樓管理室了。",
    "這次的系統升級涵蓋了後端引擎的優化，以及前端互動畫面的全面翻新。",
    "我完全支持你的決定，不管接下來遇到什麼困難，大家都會一起分擔。",
    "這顆電池經過一整天的重度使用之後，居然還剩下百分之三十五的電量。",
    "對內部的作業流程進行簡化，可以讓第一線同仁把時間留給更重要的任務。",
    "這裡的夜晚沒有都市的光害，只要抬起頭就能清楚看見滿天繁星閃爍。",
    "你的聲音聽起來好像有點沙啞，最近天氣變化大，記得多喝溫開水保重身體。",
    "這套評分標準的原則很透明，每一個項目的配分比例都寫在簡章裡面。",
    "當初幸好有聽你的勸告先存好備份，才沒有因為電腦當機而損失全部心血。",
    "他們把傳統的工藝技術跟現代的數位工具結合，創造出令人驚豔的新作品。",
    "這場討論雖然花了不少時間，但至少把各部門最在意的疑慮都攤開來說清楚了。",
    "請確認目前選取的語音模型是否正確，切換之後需要重新點擊儲存按鈕。",
    "對比舊版的渲染管線，新架構在維持畫質的同時把反應時間縮短了一半以上。",
    "這隻橘貓總是喜歡在下午兩點跳上窗台曬太陽，模樣看起來十分愜意。",
    "如果您覺得目前的語速太快或太慢，隨時都可以告訴我讓我替您微調。",
    "這些微小的調整累積起來，讓整體的使用體驗產生了相當顯著的進步。",
    "我對這道題目的解法有不同的想法，或許可以試著從反方向去推導看看。",
    "這段影片的字幕時間軸對得很準，幾乎完全貼合講者的每一個換氣停頓。",
    "不管外界的環境如何快速變遷，持續學習新知才是保持競爭力的不二法門。",
    "這個週末台北的降雨機率不高，帶上輕便的薄外套就可以安心出門逛街了。",
    "他把多年來累積的實戰筆記整理成冊，無私地分享給剛入行的學弟妹參考。",
    "我們在測試階段就發現了這個潛在的邊界錯誤，幸好趕在正式上線前修好。",
    "請幫忙把這張表格裡的數字重新加總一遍，確定小數點後兩位都完全正確。",
    "這杯現榨柳橙汁喝起來酸甜清爽，完全沒有額外添加糖漿或人工香料。",
    "對初學者而言，與其一次記憶太多艱深的術語，不如先把常見的句型練熟。",
    "系統已經順利連線到本機伺服器，現在可以開始進行即時語音互動測試了。",
    "雖然這趟旅程的路途相當遙遠，但沿途欣賞到的壯麗山景讓一切都很值得。",
    "我們的團隊注重透明與誠實的溝通文化，有任何建議都可以直接提出來討論。",
    "這部電影的配樂跟畫面節奏配合得天衣無縫，讓人看完之後久久難以忘懷。",
    "請放心把剩下的收尾工作交給我處理，你先去休息準備明天的行程吧。",
    "這個月的水電帳單金額比上個月低了許多，看來養成隨手關燈的習慣真有效。",
    "針對您剛才詢問的保固條款，官方網站的常見問答頁面有非常詳細的圖文解說。",
    "這批新採購的顯示卡散熱效能很穩定，連續跑完八小時的測試也沒有過熱降頻。",
    "我的建議是先把核心功能穩穩做好，等實際運行一段時間後再慢慢擴充細節。",
    "他對每一種音色的細微差異都很敏感，總是能很快聽出合成結果裡的小瑕疵。",
    "在陽光溫暖的午後坐在陽台喝茶看書，是一天當中讓人最放鬆的幸福時刻。",
    "我們會持續收集使用者的實際回饋，讓這個數位助理系統變得越來越聰明貼心。",
    "這份合約上的所有細節都已經確認過了，如果沒問題的話今天就能正式用印。",
    "對待學習必須保持耐心與規律的節奏，每天進步一點點就能帶來巨大的改變。",
    "請留意高鐵月台上的廣播通知，前往南港方向的列車再過三分鐘就要進站了。",
    "這支軟體的授權標示得相當明確，商業用途與研究用途的規範都各自獨立列出。",
    "你的整理能力真的讓人佩服，短短十分鐘就把這麼龐雜的資料歸納得井井有條。",
    "不管今天面臨多麼繁重的工作量，記得適時起身伸展筋骨並補充水分。",
    "這台錄音筆的抗風噪能力相當出色，即使在戶外微風吹拂下也能錄得清楚自然。",
    "我對自己這次的表現還算滿意，但相信經過更多練習之後一定能發揮得更好。",
    "這個設計巧妙地平衡了效能與功耗，在小型主機上也能展現出流暢的互動體驗。",
    "請先把麥克風的輸入增益調到適中的位置，避免講話比較大聲時產生數位削波。",
    "他們決定將剩餘的經費全部投入基層教育，希望能幫助更多偏鄉的孩子實現夢想。",
    "這段語音的咬字跟斷句都非常清楚，聽起來就像真人在身邊跟你說話一樣自然。",
    "關於這個版本的更動紀錄與驗證報告，我已經全部同步更新到專案的文件目錄下。",
    "我們期待透過更豐富的語料與更細膩的調校，徹底消除特定字詞偶發的疊音現象。",
    "明天上午九點整會在簡報室進行最終驗收，請各位負責的同仁提前十分鐘到場。",
    "這張老照片記錄了台北車站三十年前的街景，讓看過的人不禁想起許多往事。",
    "對生活保持一點好奇與熱情，就算只是平凡的日常小事也能帶來意想不到的驚喜。",
    "如果您已經準備好測試新的模型，隨時告訴我一聲，我們就立刻切換過去試聽。",
)

# Short standalone clauses/phrases (4-12 chars) matching sherpa-onnx's
# comma/period split chunks so the model handles brief utterances reliably.
_ZH_SHORT_CLAUSES = (
    "你好，我是語音助理。",
    "很高興今天為您服務。",
    "沒問題，我馬上處理。",
    "請稍等幾秒鐘就好。",
    "這樣安排非常合理。",
    "你的看法很正確。",
    "這件事對我很重要。",
    "好的，我完全理解。",
    "這樣做最有效率。",
    "請放心交給我吧。",
    "請問還有需要幫忙的嗎？",
    "今天的結果還不錯。",
    "這是最穩妥的選擇。",
    "這是我的筆記本。",
    "我們現在就開始吧。",
    "隨時歡迎再次提問。",
    "對不起，讓您久等了。",
    "這個方案我不太同意。",
    "我們再核對一次細節。",
    "請確認目前的版本。",
    "今天的會議改到四點。",
    "外面天氣非常舒適。",
    "空氣品質相當不錯。",
    "記得多喝溫開水休息。",
    "謝謝你的耐心與體諒。",
    "這個答案非常準確。",
    "請把資料存好備份。",
    "目前的進度十分順利。",
    "我已經幫你記下來了。",
    "這個問題很好解決。",
    "我們保持這樣的節奏。",
    "請問這個時間方便嗎？",
    "我覺得很有道理。",
    "看起來非常清楚明白。",
    "請對準螢幕中央位置。",
    "系統運作一切正常。",
    "音畫同步非常穩定。",
    "沒有多餘的背景雜音。",
    "可以再說詳細一點嗎？",
    "我完全支持你的決定。",
    "這樣設計相當直覺。",
    "新手也能很快上手。",
    "這點需要格外留心。",
    "先處理最重要的項目。",
    "我們先測試核心流程。",
    "請檢查麥克風的音量。",
    "請確認網路連線狀態。",
    "資料已經整理完畢了。",
    "簡報檔案隨時可用。",
    "這份報告的重點很明確。",
    "分析的邏輯相當嚴謹。",
    "請先看第一頁的圖表。",
    "這邊的數字對得很準。",
    "今天下午天氣晴朗。",
    "傍晚可能會下點小雨。",
    "出門記得帶把雨傘。",
    "路上交通有點塞車。",
    "高鐵列車準時進站了。",
    "請從三號出口右轉。",
    "大概走五分鐘就到了。",
    "那家餐廳的咖啡很香。",
    "這杯現榨果汁真清爽。",
    "中午想吃什麼料理呢？",
    "週末一起去公園散步。",
    "這個週末天氣真不錯。",
    "風景看起來特別迷人。",
    "這張照片的構圖真美。",
    "這首曲子的節奏很輕快。",
    "這本書寫得淺顯易懂。",
    "這個例子非常生動有趣。",
    "每天運動二十分鐘。",
    "早點休息保重身體。",
    "明天上午九點準時開會。",
    "請提前十分鐘到場。",
    "會議室在三樓第一間。",
    "投影設備已經開好了。",
    "文件照著編號排整齊。",
    "確認無誤後就可以送出。",
    "如果有疑問歡迎詢問。",
    "我們團隊合作得很愉快。",
    "雙方的目標完全一致。",
    "這樣溝通起來更順暢。",
    "感謝各位同仁的協助。",
    "我們對未來充滿信心。",
    "細節決定整體的品質。",
    "每天進步一點點就好。",
    "這個功能真的很實用。",
    "語音聽起來非常自然。",
    "咬字比以前清楚多了。",
    "沒有聽到明顯的破音。",
    "請問對這次調整滿意嗎？",
    "你剛才的想法非常棒。",
    "我們按照原定計畫進行。",
    "先做個簡單的記錄吧。",
    "好的，已經幫你更新。",
    "這部分我來負責處理。",
    "沒問題，一切都準備好了。",
    "請再確認一次內容。",
    "這個方向應該是對的。",
    "我對這個結果很期待。",
    "大家的意見都非常寶貴。",
    "這是最理想的情況了。",
    "麻煩您再等我一下。",
    "我馬上為您查詢資料。",
    "目前沒有任何異常狀況。",
    "請安心交給我們團隊。",
    "這樣的表現相當亮眼。",
    "今天的工作就到這邊。",
    "祝您有個美好的一天。",
    "明天見，早點休息喔。",
)

# Diverse assistant-style and conversational zh-TW sentences boosting rare
# conversational syllables such as 給 (gei3), 鬆 (song1), 訊 (xun4), 資 (zi1),
# 然 (ran2), 虛 (xu1), 助 (zhu4), 理 (li3), 簡 (jian3).
_ZH_ASSISTANT_AND_GEI3_SENTENCES = (
    "麻煩您再給我幾秒鐘，我幫您把最新的資訊整理出來。",
    "歡迎隨時把您的問題交給我，我會盡力給您清楚的回答。",
    "這款數位助理的設計目標，是帶給使用者輕鬆又自然的對話體驗。",
    "系統已經把剛才的重點傳給您，請您確認內容是否完整。",
    "如果您覺得哪邊不夠簡潔，我可以馬上再幫您修改一次。",
    "透過人工智慧與語音合成技術，虛擬角色能夠用親切的語氣跟大家聊天。",
    "請放心把繁瑣的查詢工作交給系統，您只要專注在核心決策就好。",
    "我們每天都會更新知識庫裡的最新資訊，確保能給您最準確的參考資料。",
    "這套互動介面操作起來相當輕鬆，不需要任何複雜的設定就能直接對話。",
    "聽完您的需求之後，我已經整理好幾項實用的建議要提供給您參考。",
    "他的簡報講解既簡潔又清晰，短短五分鐘就把技術原理說明白了。",
    "您可以把這份檔案寄給相關的負責人，請他們明天開會前先看過一遍。",
    "我們希望能打造一個懂台灣口音、說話自然又不會有機械感的智慧夥伴。",
    "只要您開口詢問，系統就會在第一時間給出簡短明瞭的重點摘要。",
    "這家書店總是帶給旅人一種寧靜又放鬆的閱讀氛圍。",
    "剛才那段示範影片已經給大家看得很清楚了，接下來進入問答時間。",
    "如果遇到無法回答的專業問題，助理會誠實告知而不會隨意猜測。",
    "請您把滑鼠移到畫面右側，那裡有我剛剛推送給您的步驟清單。",
    "學習新工具最重要的是放輕鬆，每天練習一點自然就會越來越熟練。",
    "這位虛擬導覽員不僅熟悉館內展區資訊，還能支援中英文雙語互動。",
    "把複雜的數據轉化成簡單易懂的圖表，能帶給團隊極大的幫助。",
    "謝謝您今天給我們的寶貴回饋，這些意見對後續優化非常關鍵。",
    "我已經幫您把會議紀錄寄給所有與會同事，大家待會兒就能收到信件。",
    "這首輕快的音樂非常適合在工作累了的時候聽，能讓心情立刻放鬆下來。",
    "無論您需要查詢即時天氣或是大眾運輸資訊，我都可以立刻協助您。",
    "系統的語音辨識引擎能準確捕捉您的語意，並用流暢的中文自然回應。",
    "請給自己一點時間調整步調，過度緊張反而容易忘記原本準備好的台詞。",
    "這份技術報告提供給研發部門參考，裡面詳列了延遲與準確率的統計數據。",
    "好的溝通建立在雙向理解之上，先聽清楚對方需求才能給出好建議。",
    "週末去森林步道走走，呼吸新鮮空氣，總是能帶給身心滿滿的能量。",
    "如果這組帳號權限還沒開啟，請聯絡系統管理員請他補發通知給您。",
    "這套離線方案不需要連上雲端伺服器，依然能維持簡潔清晰的語音互動。",
    "他把多年經驗寫成一篇篇實用的文章，免費分享給剛入行的新手閱讀。",
    "今天的展示就到這裡告一段落，接下來就把時間交給現場的技術團隊。",
    "這台螢幕的顯示效果十分清晰，拿來呈現即時影像跟數據看板最適合不過。",
    "請幫忙把桌上的聯絡資訊轉交給櫃檯人員，他們等一下會統一建檔。",
    "就算面對突發的緊急狀況，保持輕鬆冷靜的頭腦還是能找到解決辦法。",
    "這套智慧問答系統能幫助客服人員大幅減少重複解答基本問題的時間。",
    "如果你對這份簡報還有任何疑問，歡迎直接寫信給我或留言討論。",
    "清晰的邏輯與簡潔的表達方式，是讓聽眾瞬間抓到重點的最佳技巧。",
)

_PHONETIC_RICH_ZH_TW = (
    "科學園區今年引進新型半導體封裝設備，良率明顯提升百分之五點四。",
    "醫療團隊透過高解析影像輔助診斷，讓病患能更早接受精準治療。",
    "圖書館三樓安靜閱覽室禁止攜帶飲料與食物，借還書籍請使用自助機台。",
    "餐廳主廚精選當季新鮮蔬果與海鮮食材，烹調出清淡爽口的在地風味料理。",
    "金融機構提醒民眾切勿點擊來路不明的簡訊連結，以免帳號密碼遭到竊取。",
    "博物館特展展出珍貴青銅器與古代書畫，現場提供免費語音導覽耳機租借。",
    "建築師採用大片落地玻璃與綠色植栽設計，大幅減少夏季冷氣空調耗電量。",
    "運動中心游泳池與健身房每日清晨六點開放，週一上午例行消毒保養。",
    "學生社團舉辦慈善義賣與二手書籍交換活動，所得全數捐贈偏鄉小學圖書室。",
    "消防局宣導居家安裝住宅用火災警報器，並定期檢查瓦斯管線是否老化漏氣。",
    "農會推廣有機茶葉與高山水蜜桃禮盒，支持青年返鄉發展智慧農業技術。",
    "法院判決強調契約雙方必須誠實履行義務，不得任意毀約或隱匿重要事實。",
    "音樂廳週末邀請交響樂團演出經典曲目，曲風涵蓋浪漫派與現代爵士組曲。",
    "研發部門測試新型固態電池在低溫環境下的放電曲線與循環壽命表現。",
    "心理諮商師建議保持規律作息與適度運動，有助緩解長期累積的工作壓力。",
    "電信公司宣布偏遠山區基地台擴建完工，大幅改善緊急救援時的通訊品質。",
    "百貨公司週年慶推出滿額折抵與銀行聯名卡優惠，吸引大批消費者排隊採購。",
    "環保局鼓勵自備購物袋與環保餐具，減少一次性塑膠製品對海洋生態的衝擊。",
    "工程師逐行比對測試紀錄檔與網路封包追蹤數據，終於釐清偶發斷線的原因。",
    "攝影愛好者清晨登上合歡山主峰拍攝日出雲海，夜晚還捕捉到清晰的銀河。",
    "郵局包裹採用防撞氣泡紙妥善包裝，預計明天中午前即可配送至收件地址。",
    "烘焙坊每天現烤核桃雜糧麵包、脆皮可頌與濃郁肉桂捲，香氣四溢。",
    "這套即時語音系統支援繁體中文與美式英語雙語自然穿插，延遲低於半秒。",
    "麻煩您幫忙確認麥克風收音音量是否過小，或者把背景降噪閾值稍微調低。",
    "雖然外頭下著滂沱大雨，室內展覽區依然擠滿熱愛科技創作的參觀群眾。",
    "無論您需要撰寫簡報大綱、摘要pdf重點，或是查詢最新法規條文都可以協助。",
    "請小心搬運脆弱的玻璃儀器與光學鏡頭，避免劇烈震動造成校準偏移。",
    "為了確保夜間值班人員順利交接，所有異常事件必須詳細記錄於交班日誌中。",
    "他們決定趁著秋季氣候宜人，安排四天三夜的環島火車之旅放鬆身心。",
    "這款輕量化聲學模型僅使用四顆 CPU 執行緒就能穩定合成流暢語音。",
    "面對突發的流量高峰與複雜的跨部門溝通，冷靜拆解步驟往往最有效率。",
    "奶奶喜歡在陽光灑落的陽台修剪蘭花與薄荷葉，順便泡一壺烏龍茶品茗。",
    "研究報告指出全球再生能源裝置容量持續創新高，儲能電網扮演關鍵角色。",
    "請將舊款電池回收投入指定桶內，切勿混入一般垃圾壓縮車造成危險。",
    "這支軟體更新修復了記憶體洩漏、緩衝區溢位與部分冷僻字詞的斷詞瑕疵。",
)

_ZH_SCENARIO_TOPICS = (
    ("展區導覽", "A 館智慧互動體驗區", "每日上午九點到下午六點"),
    ("交通接駁", "高鐵左營站二號出口", "每隔十五分鐘發出一班"),
    ("天氣預報", "台北市信義區今日氣溫二十六度", "傍晚降雨機率百分之三十"),
    ("系統架構", "本機推論引擎與離線語音模組", "不需依賴外部雲端金鑰"),
    ("知識庫檢索", "企業內部產品手冊與常見問題", "平均不到半秒即可完成回答"),
    ("會議室預約", "三樓第一會議室與投影設備", "今天下午兩點十五分可直接使用"),
    ("客戶服務", "帳號開通與權限設定流程", "通常會在三分鐘內完成確認"),
    ("硬體效能", "邊緣運算節點與即時影像管線", "可穩定維持每秒二十五張畫面"),
)

_ZH_TEMPLATES = (
    "關於{topic}，目前的主要服務地點在{detail}，開放時間為{extra}。",
    "好的，我為您查詢到{topic}的最新資訊：{detail}，{extra}。",
    "您提到的{topic}已經完成設定，範圍包含{detail}，時間則是{extra}。",
    "如果要確認{topic}的細節，建議先查看{detail}，另外要注意{extra}。",
)

_ZH_CODE_SWITCH_TEMPLATES = (
    "目前 {component} 正在 {device} 上運行，整體 {metric} 表現相當穩定。",
    "您可以透過 {component} 呼叫 {action}，這個流程在 {device} 上只需零點五秒。",
    "針對 {component} 的測試結果顯示，{device} 能夠順利支撐 {action}。",
    "請幫我打開 {component} 設定面板，並確認 {action} 已經成功啟動。",
)

_COMPONENTS = ("Nova Avatar", "Matcha TTS", "Whisper ASR", "RAGFlow 知識庫", "MuseTalk", "WebRTC")
_DEVICES = ("Jetson Orin", "本機 CPU", "GPU 推論管線", "離線伺服器")
_METRICS = ("RFT 延遲", "音畫同步", "口音清晰度", "記憶體佔用")
_ACTIONS = ("雙語語音合成", "繁體中文即時辨識", "知識問答看板更新", "API 自動查詢")

_EN_SENTENCES = (
    "Welcome to Nova Avatar. How can I help you today?",
    "Let me check the exhibition schedule and details for you.",
    "Everything is running locally on edge hardware with low latency.",
    "Feel free to ask questions in either Traditional Chinese or English.",
    "I have updated the summary board with the key points you requested.",
    "The audio and video streams are synchronized at twenty five frames per second.",
    "Please let me know if you would like a quick technical walkthrough.",
    "We can review the weather forecast, meeting schedule, or system metrics.",
    "Hold on a moment while I retrieve the latest document from the knowledge base.",
    "Thank you for visiting today, and enjoy the interactive demonstration.",
    "Could you speak a little closer to the microphone so I can hear clearly?",
    "Voice synthesis runs completely on the CPU without competing for GPU memory.",
    "Let me switch to English mode and walk through the architecture step by step.",
)


def _estimate_seconds(text: str) -> float:
    ascii_words = sum(1 for tok in text.split() if tok.isascii())
    cjk_chars = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return max(1.6, round(cjk_chars / 4.3 + ascii_words / 2.3 + 0.3, 2))


def _build_phonetic_coverage_sentences(
    existing_texts: list[str],
    *,
    max_sentences: int = 220,
) -> list[str]:
    """Generate natural carrier sentences covering unseen Mandarin pinyin+tone syllables."""
    repo_root = Path(__file__).resolve().parents[2]
    zh_lex = repo_root / "models/tts/matcha-icefall-zh-en/lexicon-zh.txt"
    tokens_path = repo_root / "models/tts/matcha-icefall-zh-en/tokens.txt"
    if not (zh_lex.is_file() and tokens_path.is_file()):
        return []

    import sys

    tools_dir = Path(__file__).resolve().parent
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    from lexicon_utils import load_tokens, text_to_phoneme_ids

    try:
        from opencc import OpenCC
        t2s = OpenCC("t2s")
        s2tw = OpenCC("s2tw")
    except ImportError:
        t2s = s2tw = None

    tok_to_id = load_tokens(tokens_path)
    word_phons: list[tuple[str, set[int]]] = []
    word_dict: dict[str, list[str]] = {}
    all_zh_pids: set[int] = set()
    for line in zh_lex.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        w, ph = parts[0], parts[1:]
        if not all(p in tok_to_id for p in ph):
            continue
        word_dict.setdefault(w, ph)
        pids = {tok_to_id[p] for p in ph}
        all_zh_pids.update(pids)
        if 2 <= len(w) <= 3 and all("\u4e00" <= ch <= "\u9fff" for ch in w):
            tw_w = s2tw.convert(w) if s2tw is not None else w
            # Skip archaic/rare words with non-roundtrip variants
            word_phons.append((tw_w, pids))

    from collections import Counter

    pid_counts: Counter[int] = Counter()
    for text in existing_texts:
        pid_counts.update(text_to_phoneme_ids(text, word_dict, tok_to_id, converter=t2s))

    carriers = (
        "這次討論的主題包含{w1}、{w2}與{w3}，我們來逐一確認細節。",
        "在整理{w1}的筆記時，常常會同時提到{w2}和{w3}。",
        "關於{w1}與{w2}的應用案例，其實和{w3}非常接近。",
        "請幫我在看板上記錄{w1}、{w2}，還有下一步的{w3}。",
        "如果想深入比較{w1}跟{w2}的差異，記得把{w3}也列入參考。",
        "老師在課堂上舉了{w1}的例子，又順便補充了{w2}與{w3}的概念。",
        "這份報告同時分析{w1}、{w2}的變化趨勢，並說明{w3}的影響。",
        "平時聊天提到{w1}或{w2}的時候，大家通常也會聯想到{w3}。",
    )
    out: list[str] = []
    # Deduplicate by (tw_w) and sample up to 12,000 common 2-char phrases first
    seen_words: set[str] = set()
    two_char = [(w, pids) for w, pids in word_phons if len(w) == 2]
    other_w = [(w, pids) for w, pids in word_phons if len(w) != 2]
    ordered_pool = two_char + other_w
    candidates = ordered_pool if len(ordered_pool) <= 12000 else ordered_pool[:: max(1, len(ordered_pool) // 12000)]

    target_min_count = 12
    for idx in range(max_sentences):
        low_pids = {pid for pid in all_zh_pids if pid_counts[pid] < target_min_count}
        if not low_pids:
            break
        chosen_words: list[str] = []
        for _ in range(3):
            best_w, best_score, best_pids = None, 0.0, set()
            for w, pids in candidates:
                if w in chosen_words or w in seen_words:
                    continue
                overlap = pids & low_pids
                if not overlap:
                    continue
                # Strongly prioritize rarer syllables (count == 0..5 before count == 11)
                score = sum(1.0 / (1.0 + pid_counts[p]) for p in overlap)
                if score > best_score:
                    best_w, best_score, best_pids = w, score, pids
                    if score >= 2.0:
                        break
            if best_w is None or best_score <= 0.0:
                break
            chosen_words.append(best_w)
            seen_words.add(best_w)
            pid_counts.update(best_pids)
            low_pids -= best_pids
        if len(chosen_words) < 3:
            break
        tmpl = carriers[idx % len(carriers)]
        out.append(tmpl.format(w1=chosen_words[0], w2=chosen_words[1], w3=chosen_words[2]))
    return out


def generate_corpus(
    *,
    target_hours: float = 1.0,
    seed: int = 42,
    preserve_path: Path | None = None,
) -> list[dict]:
    rng = random.Random(seed)
    pool: list[tuple[str, str]] = []
    seen: set[str] = set()
    preserved: list[dict] = []

    if preserve_path is not None and preserve_path.is_file():
        for line in preserve_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            cleaned = " ".join(str(item["text"]).split())
            if cleaned not in seen:
                seen.add(cleaned)
                preserved.append(item)

    def add(lang: str, text: str) -> None:
        cleaned = " ".join(text.split())
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            pool.append((lang, cleaned))

    for text in _ZH_GREETINGS:
        add("zh-TW", text)

    for text in _PHONETIC_RICH_ZH_TW:
        add("zh-TW", text)

    for text in _TRANSIT_SENTENCES:
        add("zh-TW", text)

    for text in _ZH_CONVERSATIONAL_DE_DUI:
        add("zh-TW", text)

    for text in _ZH_SHORT_CLAUSES:
        add("zh-TW", text)

    for text in _ZH_ASSISTANT_AND_GEI3_SENTENCES:
        add("zh-TW", text)

    for place, cond, low, high in _TAIWAN_CITIES_WEATHER:
        for tmpl in _WEATHER_TEMPLATES:
            add("zh-TW", tmpl.format(place=place, cond=cond, low=low, high=high))

    for topic, detail, extra in _ZH_SCENARIO_TOPICS:
        for tmpl in _ZH_TEMPLATES:
            add("zh-TW", tmpl.format(topic=topic, detail=detail, extra=extra))

    for comp in _COMPONENTS:
        for dev in _DEVICES:
            for met in _METRICS:
                for act in _ACTIONS:
                    for tmpl in _ZH_CODE_SWITCH_TEMPLATES:
                        add(
                            "zh-TW-en",
                            tmpl.format(component=comp, device=dev, metric=met, action=act),
                        )

    polite_prefixes = ("好的，", "沒問題，", "麻煩您等一下，", "我了解，", "報告您，")
    actions = (
        "今天台北氣溫約二十四度，非常適合外出參觀。",
        "您的簡報檔案已經準備完畢，隨時可以開始。",
        "高鐵列車預計十點二十分抵達，請提前前往月台。",
        "這個問題我們可以從系統延遲與畫質兩個方向來看。",
        "如果需要進一步調整語速，可以在設定面板直接修改。",
        "請問要幫您把這段重點也整理到右側看板嗎？",
        "目前離線模型已經載入完成，沒有連線金鑰也能正常對話。",
        "這份技術說明包含台灣繁體中文與美式英語的雙語測試案例。",
    )
    for pref in polite_prefixes:
        for act in actions:
            add("zh-TW", f"{pref}{act}")

    for text in _EN_SENTENCES:
        add("en-US", text)

    en_intros = ("Sure,", "Got it,", "Right away,", "Of course,")
    en_clauses = (
        "the local speech pipeline is ready for your next question.",
        "I can switch back to Traditional Chinese whenever you prefer.",
        "the Jetson Orin runtime is keeping audio latency under half a second.",
        "let me summarize those API results on your screen.",
    )
    for intro in en_intros:
        for clause in en_clauses:
            add("en-US", f"{intro} {clause}")

    seed_texts = [item["text"] for item in preserved] + [text for _, text in pool]
    for cov_text in _build_phonetic_coverage_sentences(seed_texts, max_sentences=340):
        add("zh-TW", cov_text)

    # Rank new candidates to maximize newly covered CJK characters first
    covered_chars: set[str] = set()
    for item in preserved:
        covered_chars.update(ch for ch in item["text"] if "\u4e00" <= ch <= "\u9fff")

    zh_rich = [item for item in pool if item[0] == "zh-TW"]
    zh_mixed = [item for item in pool if item[0] == "zh-TW-en"]
    en_items = [item for item in pool if item[0] == "en-US"]
    rng.shuffle(zh_rich)
    rng.shuffle(zh_mixed)
    rng.shuffle(en_items)
    zh_mixed = zh_mixed[: max(10, len(zh_rich) // 6)]

    # Greedy diversity sort for zh_rich so every city/weather/phonetically rich
    # sentence covering unseen characters gets picked first!
    ordered_zh: list[tuple[str, str]] = []
    remaining = list(zh_rich)
    while remaining:
        best_idx = max(
            range(len(remaining)),
            key=lambda i: sum(
                1 for ch in remaining[i][1] if "\u4e00" <= ch <= "\u9fff" and ch not in covered_chars
            ),
        )
        chosen = remaining.pop(best_idx)
        new_chars = {ch for ch in chosen[1] if "\u4e00" <= ch <= "\u9fff" and ch not in covered_chars}
        if not new_chars:
            ordered_zh.append(chosen)
            ordered_zh.extend(remaining)
            break
        covered_chars.update(new_chars)
        ordered_zh.append(chosen)

    # Interleave rich zh-TW, remaining code-switch, and English cleanly
    combined_zh: list[tuple[str, str]] = []
    ri = mi = 0
    while ri < len(ordered_zh) or mi < len(zh_mixed):
        if ri < len(ordered_zh):
            combined_zh.append(ordered_zh[ri])
            ri += 1
        if ri < len(ordered_zh):
            combined_zh.append(ordered_zh[ri])
            ri += 1
        if mi < len(zh_mixed):
            combined_zh.append(zh_mixed[mi])
            mi += 1

    target_seconds = max(60.0, target_hours * 3600.0)
    selected: list[dict] = list(preserved)
    acc_seconds = sum(float(item.get("est_seconds", 4.0)) for item in selected)
    zi = ei = 0
    step = 0
    while acc_seconds < target_seconds and (zi < len(combined_zh) or ei < len(en_items)):
        use_en = (step % 7 == 6 or zi >= len(combined_zh)) and ei < len(en_items)
        lang, text = en_items[ei] if use_en else combined_zh[zi]
        if use_en:
            ei += 1
        else:
            zi += 1
        step += 1
        est_s = _estimate_seconds(text)
        selected.append(
            {
                "id": f"utt_{len(selected):05d}",
                "language": lang,
                "text": text,
                "est_seconds": est_s,
            }
        )
        acc_seconds += est_s

    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=1.0, help="Target corpus duration in hours")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--preserve-existing",
        action="store_true",
        help="Keep existing output entries intact and append new utterances after them",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/tts/distill/corpus.jsonl"),
        help="Output JSONL corpus path",
    )
    args = parser.parse_args()

    items = generate_corpus(
        target_hours=args.hours,
        seed=args.seed,
        preserve_path=args.output if args.preserve_existing else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    est_hours = sum(item["est_seconds"] for item in items) / 3600.0
    print(f"Wrote {len(items)} utterances (~{est_hours:.2f}h est) -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
