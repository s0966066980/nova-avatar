# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

import logging
import os
from datetime import datetime

# 配置日誌器
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# 確保 logs 資料夾存在
log_dir = 'logs'
os.makedirs(log_dir, exist_ok=True)

# 日誌檔名加上時間
date_str = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
log_filename = f'nova-avatar_{date_str}.log'
log_path = os.path.join(log_dir, log_filename)

fhandler = logging.FileHandler(log_path)
fhandler.setFormatter(formatter)
fhandler.setLevel(logging.INFO)
logger.addHandler(fhandler)

# handler = logging.StreamHandler()
# handler.setLevel(logging.DEBUG)
# sformatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
# handler.setFormatter(sformatter)
# logger.addHandler(handler)
