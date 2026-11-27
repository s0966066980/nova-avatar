# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Check restricted self-disclosures at complete, human-visible boundaries."""
from __future__ import annotations

import re


_MODEL_RESTRICTION = re.compile(
    r"(?:不得|禁止|不允許|不提供|不要|不可|不能|do\s+not|don't|must\s+not|never|forbid)"
    r"[^\n。.!;；]{0,120}(?:LLM|語言模型|模型資訊|模型信息|model\s+(?:information|details|identity)|underlying\s+model)"
    r"|(?:LLM|語言模型|model\s+(?:information|details|identity))[^\n。.!;；]{0,80}"
    r"(?:must\s+not|不得|禁止)", re.IGNORECASE,
)
_SELF_MODEL = re.compile(
    r"\bI(?:\s+am|'m|’m)\s+(?:an?\s+)?(?:large\s+language\s+model|language\s+model|LLM|AI\s+model|open[-\s]+weights?\s+model|foundation\s+model|multimodal\s+model)\b"
    r"|\b(?:my|our)\s+(?:(?:underlying|foundation|language|AI)\s+)?"
    r"(?:model|architecture|training|modules?|providers?|developers?|creators?)\b"
    r"|我(?:是|為)[^。！？\n]{0,60}(?:語言模型|LLM|AI模型)"
    r"|(?:我的|我們的|本(?:系統|助手)的)(?:底層)?(?:模型|架構|訓練|模組|開發商)", re.IGNORECASE,
)
_SELF_ORIGIN = re.compile(
    r"\bI(?:(?:\s+(?:was|am|have\s+been))|['’]m)?\s+(?:[^.!?;\n]{0,100}?\s+)?"
    r"(?:created|developed|built|made|trained|powered)\s+(?:by|at)\s+(?P<en>[^.!?;\n]+)"
    r"|(?P<reverse>[^.!?;\n]{1,100})\s+(?:created|developed|built|made|trained)\s+me\b"
    r"|我(?:是)?(?:由|被)(?P<zh>[^。！？\n]{1,100}?)(?:開發|开发|建立|建構|創造|创造|創建|创建|訓練|训练)",
    re.IGNORECASE,
)
_IDENTITY_QUESTION = re.compile(
    r"自我介紹|介紹你自己|你是誰|誰.*(?:開發|創造).*你|你的.*(?:開發者|來源|模型)"
    r"|introduce\s+yourself|who\s+(?:are|created|developed|made|built)\s+you"
    r"|your\s+(?:creator|developer|provider|model)", re.IGNORECASE,
)
_BARE_ORIGIN = re.compile(r"^\s*(?:created|developed|trained|built|made|powered)\s+by\b", re.IGNORECASE)
_PUBLIC_CREATOR = re.compile(
    r'(?:created|developed|made|built)\s+by\s+(?P<en>[^.!?;\n]+)'
    r'|由(?P<zh>[^。！？\n]+?)(?:開發|創造|开发|创造)', re.IGNORECASE,
)


def _public_creators(role: str) -> set[str]:
    creators = set()
    for sentence in re.split(r'[.!?。！？\n]', role):
        if re.search(
            r"不得|禁止|不能|不可|不允許|不允许|不要|不提供|\b(?:not|never|forbid)\b|don't"
            r'|LLM|language\s+model|語言模型|语言模型|底層|underlying|foundation',
            sentence, re.IGNORECASE,
        ):
            continue
        for match in _PUBLIC_CREATOR.finditer(sentence):
            creators.add(next(value for value in match.groupdict().values() if value).strip().casefold())
    return creators


class IdentityPolicy:
    """Enforce the recognized model-disclosure restriction without vendor lists.

    This is a bounded guard for self-identity/origin claims, not a parser or
    guarantee for arbitrary natural-language restrictions. Third-party factual
    references remain intact. The complete sentence must pass before preview,
    TTS, board delivery or history can receive it.
    """

    def __init__(self, profile, *, model: str = '', user_message: str = ''):
        self.enabled = bool(_MODEL_RESTRICTION.search(str(getattr(profile, 'restriction_prompt', '') or '')))
        self.locale = getattr(profile, 'output_locale', 'zh-TW')
        self.name = str(getattr(profile, 'assistant_name', '') or '').strip()
        self.public_creators = _public_creators(str(getattr(profile, 'system_prompt', '') or ''))
        self.identity_question = bool(_IDENTITY_QUESTION.search(user_message))
        self.details_requested = bool(re.search(
            r"(?:誰|谁).*(?:開發|开发|創造|创造)|(?:模型|開發者|开发者|開發商|开发商|創作者|创造者)"
            r"|\bwho\s+(?:created|developed|made|built)\s+you\b"
            r"|\b(?:creator|developer|provider|model|modules?)\b", user_message, re.IGNORECASE,
        ))
        self_reference = bool(re.search(
            r'你[^。！？\n]*(?:模型|模組|开发|開發)|(?:誰|谁)[^。！？\n]*(?:開發|开发|創造|创造)[^。！？\n]*你'
            r'|\bwho\s+(?:created|developed|made|built)\s+you\b'
            r'|\byour\s+(?:creator|developer|provider|model|modules?)\b'
            r'|\b(?:model|modules?|provider|developer)\b[^.!?\n]*\byou\b'
            r'|\byou\b[^.!?\n]*\b(?:model|modules?|provider|developer)\b', user_message, re.IGNORECASE,
        ))
        explicit_model_question = bool(re.search(r'模型|模組|\b(?:model|modules?)\b', user_message, re.IGNORECASE))
        self.refuse_request = self.enabled and self_reference and self.details_requested and (explicit_model_question or not self.public_creators)
        stem = re.match(r'[A-Za-z]{3,}', str(model).rsplit('/', 1)[-1])
        self._model_claim = re.compile(
            r"(?:\bI(?:\s+am|'m|’m)|\bmy\s+(?:name|model)\s+is|我是)\s*"
            + re.escape(stem.group()) + r"(?:\b|\d)", re.IGNORECASE,
        ) if stem else None

    def blocks(self, text: str) -> bool:
        if not self.enabled or not text:
            return False
        if _SELF_MODEL.search(text) or (self._model_claim and self._model_claim.search(text)):
            return True
        for match in _SELF_ORIGIN.finditer(text):
            creator = next(value for value in match.groupdict().values() if value).strip()
            # A public creator expressly supplied by the configured role is
            # distinct from inventing the foundation model's training identity.
            if creator.casefold() not in self.public_creators:
                return True
        return self.identity_question and bool(_BARE_ORIGIN.search(text))

    def refusal(self, *, include_name: bool = True) -> str:
        if self.locale == 'en-US':
            return (f'I am {self.name}. ' if self.name and include_name else '') + 'I cannot share internal system details.'
        return (f'我是{self.name}。' if self.name and include_name else '') + '內部系統的詳細資訊不便提供。'

    def sanitize(self, text: str, *, identity_already_visible: bool = False) -> str:
        if not self.blocks(text):
            return text
        # Keep permitted role/capability sentences instead of replacing an
        # entire introduction because one sentence disclosed model metadata.
        sentences = [m.group() for m in re.finditer(r'.+?(?:[.!?](?=\s|$)|[。！？]|$)', text, re.DOTALL)]
        safe = ''.join(sentence for sentence in sentences if not self.blocks(sentence))
        if not self.details_requested and safe.strip():
            replacement = ''
        elif not self.details_requested and self.identity_question and self.name:
            replacement = '' if identity_already_visible else (
                f'I am {self.name}.' if self.locale == 'en-US' else f'我是{self.name}。'
            )
        else:
            replacement = self.refusal(include_name=not self.name or self.name.casefold() not in safe.casefold())
        replaced = False
        result = []
        for sentence in sentences:
            if self.blocks(sentence):
                if not replaced:
                    if replacement:
                        result.append((' ' if result else '') + replacement)
                    replaced = True
            else:
                result.append(sentence)
        cleaned = ''.join(result).strip()
        if not cleaned and identity_already_visible and not self.details_requested:
            return ''
        return cleaned or self.refusal()

    def board_item(self, title: str, content: str) -> tuple[str, str]:
        if self.blocks(title + '\n' + content):
            return ('Role information' if self.locale == 'en-US' else '角色資訊', self.refusal())
        return title, content
