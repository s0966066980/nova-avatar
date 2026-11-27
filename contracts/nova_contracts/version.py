# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Version of the cross-layer contracts.

Bump it on any change a layer on the other side of a loopback request would
notice. Once a layer runs as its own process it reports this value on
``/health`` and the core refuses a service whose value differs (ADR 0027).
"""

CONTRACT_VERSION = "1"
