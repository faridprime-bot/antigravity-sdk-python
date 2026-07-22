# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Core trigger interface for the Google Antigravity SDK.

A Trigger is a long-lived async function that runs alongside an agent
session. It reacts to external events (cron, file changes, webhooks)
and pushes messages back into the agent.
"""

from __future__ import annotations

import enum
import inspect
from typing import Awaitable, Callable, Protocol

import pydantic

from google.antigravity.types import TriggerDelivery


class TriggerConnection(Protocol):

  async def send_trigger_notification(self, content: str) -> None:
    ...

  async def wait_for_idle(self) -> None:
    ...

  async def cancel(self) -> None:
    ...


class TriggerContext:
  """Handle provided to every trigger at startup.

  Provides the capability to send messages to the agent. One
  TriggerContext is created per trigger.
  """

  def __init__(
      self,
      connection: TriggerConnection,
  ) -> None:
    self._connection = connection

  async def send(
      self,
      content: str,
      delivery: TriggerDelivery = TriggerDelivery.SEND_IMMEDIATELY,
  ) -> None:
    """Sends a message to the agent.

    Args:
      content: The message content.
      delivery: Controls when the message is delivered relative to any turn
        currently in progress. SEND_IMMEDIATELY (default) sends right away.
        WAIT_IDLE waits for the agent to finish its current turn first.
        INTERRUPT cancels the current turn before sending.
    """
    if delivery == TriggerDelivery.WAIT_IDLE:
      await self._connection.wait_for_idle()
    elif delivery == TriggerDelivery.INTERRUPT:
      await self._connection.cancel()
    await self._connection.send_trigger_notification(content)


# A Trigger is any async function that accepts a TriggerContext.
Trigger = Callable[[TriggerContext], Awaitable[None]]


def trigger(func: Callable[[TriggerContext], Awaitable[None]]):
  """Decorator for Triggers.

  Validates that the function is async and accepts exactly one argument
  (TriggerContext). Adds __is_trigger__ = True metadata.

  Args:
    func: The async function to wrap as a trigger.

  Returns:
    The original function with __is_trigger__ attribute set.
  """
  if not inspect.iscoroutinefunction(func):
    raise ValueError("Trigger must be an async function")

  sig = inspect.signature(func)
  params = list(sig.parameters.values())
  if len(params) != 1:
    raise ValueError("Trigger must accept exactly one parameter")

  setattr(func, "__is_trigger__", True)
  return func


class FileChangeKind(str, enum.Enum):
  """Kind of filesystem change detected by a file-watching trigger."""

  ADDED = "added"
  MODIFIED = "modified"
  DELETED = "deleted"


class FileChange(pydantic.BaseModel):
  """A single filesystem change detected by a file-watching trigger.

  Attributes:
    kind: The type of change (added, modified, deleted).
    path: Absolute path to the changed file.
  """

  model_config = pydantic.ConfigDict(frozen=True)

  kind: FileChangeKind
  path: str
