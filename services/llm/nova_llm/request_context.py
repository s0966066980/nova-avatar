# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Backend-owned, request-only instructions; str() retains the original question."""

class RequestQuestion(str):
    def __new__(cls, question, instructions):
        value = super().__new__(cls, str(question))
        value.request_instructions = instructions
        if hasattr(question, 'parts'):
            value.parts = list(question.parts)
        return value
