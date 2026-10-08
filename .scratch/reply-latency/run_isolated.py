# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Audio-first canary; capture current settings without changing production."""
from dataclasses import asdict
from pathlib import Path
import logging
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.config.loader import load_config
from src.config import overrides
from src.utils.logging import logger


class RedactStartupConfig(logging.Filter):
    def filter(self, record):
        return not record.getMessage().startswith("已載入配置:")


def main():
    config = load_config("config/config_jetson.yaml")
    config.app.listenport = 8011
    config.llm.llamacpp_port = 8091
    config.llm.base_url = "http://127.0.0.1:8091/v1"
    config.video.max_height = 960
    config.model.musetalk.vae_engine_path = str(ROOT / ".scratch/avatar-performance/vae.engine")
    config.reply_streaming.enabled = True
    config.reply_streaming.decoupled_audio_clock = True
    short_answer = "第一句先用約 10–20 字直接給出實質答案，以句號結束，再補充說明；不以占位語代替回答。"
    if short_answer not in config.llm.reply_rules.speech:
        config.llm.reply_rules.speech += "\n" + short_answer
    directory = Path(__file__).resolve().parent
    path = directory / "effective-private.yaml"
    path.write_text(yaml.safe_dump(asdict(config), allow_unicode=True, sort_keys=False))
    path.chmod(0o600)
    overrides.RUNTIME_OVERRIDES_FILE = directory / "runtime-private.yaml"
    logger.addFilter(RedactStartupConfig())
    print("isolated port=8011 llm_port=8091 max_height=960 TensorRT=True independent_audio=True", flush=True)
    sys.argv = [sys.argv[0], "--config", str(path)]
    from src.server.app import main as serve
    serve()


if __name__ == "__main__":
    main()
