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

"""Tests for TriggerContext and delivery modes."""

import unittest
from unittest import mock

import pydantic

from google.antigravity.connections import connection
from google.antigravity.triggers import triggers


class TriggerContextTest(unittest.IsolatedAsyncioTestCase):

  def _make_mock_connection(self):
    conn = mock.AsyncMock(spec=connection.Connection)
    conn.send_trigger_notification = mock.AsyncMock()
    return conn

  async def test_send_calls_connection_send_trigger_notification(self):
    conn = self._make_mock_connection()
    ctx = triggers.TriggerContext(connection=conn)

    await ctx.send("hello")

    conn.send_trigger_notification.assert_called_once_with("hello")

  async def test_send_immediately_does_not_wait_or_cancel(self):
    conn = self._make_mock_connection()
    ctx = triggers.TriggerContext(connection=conn)

    await ctx.send("hello", delivery=triggers.TriggerDelivery.SEND_IMMEDIATELY)

    conn.wait_for_idle.assert_not_called()
    conn.cancel.assert_not_called()
    conn.send_trigger_notification.assert_called_once_with("hello")

  async def test_wait_idle_waits_before_sending(self):
    conn = self._make_mock_connection()
    manager = mock.Mock()
    manager.attach_mock(conn.wait_for_idle, "wait_for_idle")
    manager.attach_mock(
        conn.send_trigger_notification, "send_trigger_notification"
    )
    ctx = triggers.TriggerContext(connection=conn)

    await ctx.send("hello", delivery=triggers.TriggerDelivery.WAIT_IDLE)

    conn.wait_for_idle.assert_called_once()
    conn.cancel.assert_not_called()
    self.assertEqual(
        [call[0] for call in manager.mock_calls],
        ["wait_for_idle", "send_trigger_notification"],
    )

  async def test_interrupt_cancels_before_sending(self):
    conn = self._make_mock_connection()
    manager = mock.Mock()
    manager.attach_mock(conn.cancel, "cancel")
    manager.attach_mock(
        conn.send_trigger_notification, "send_trigger_notification"
    )
    ctx = triggers.TriggerContext(connection=conn)

    await ctx.send("hello", delivery=triggers.TriggerDelivery.INTERRUPT)

    conn.cancel.assert_called_once()
    conn.wait_for_idle.assert_not_called()
    self.assertEqual(
        [call[0] for call in manager.mock_calls],
        ["cancel", "send_trigger_notification"],
    )


class TriggerTypeTest(unittest.TestCase):

  def test_trigger_is_callable_type(self):
    """Verify that an async def is a valid Trigger."""

    async def my_trigger(ctx: triggers.TriggerContext) -> None:
      pass

    # Type check: should be assignable to Trigger.
    trigger: triggers.Trigger = my_trigger
    self.assertTrue(callable(trigger))


class TriggerDecoratorTest(unittest.TestCase):

  def test_valid_trigger_accepted(self):
    @triggers.trigger
    async def my_trigger(ctx: triggers.TriggerContext) -> None:
      del ctx

    self.assertTrue(getattr(my_trigger, "__is_trigger__", False))

  def test_not_async_raises_value_error(self):
    def sync_trigger(ctx: triggers.TriggerContext) -> None:
      del ctx

    with self.assertRaises(ValueError) as cm:
      triggers.trigger(sync_trigger)
    self.assertEqual(str(cm.exception), "Trigger must be an async function")

  def test_wrong_signature_raises_value_error(self):
    async def no_arg_trigger() -> None:
      pass

    with self.assertRaises(ValueError) as cm:
      triggers.trigger(no_arg_trigger)
    self.assertEqual(
        str(cm.exception), "Trigger must accept exactly one parameter"
    )

    async def multi_arg_trigger(
        ctx: triggers.TriggerContext, extra: int
    ) -> None:
      del ctx, extra

    with self.assertRaises(ValueError) as cm:
      triggers.trigger(multi_arg_trigger)
    self.assertEqual(
        str(cm.exception), "Trigger must accept exactly one parameter"
    )


class FileChangeTest(unittest.TestCase):

  def test_file_change_is_immutable(self):
    change = triggers.FileChange(
        kind=triggers.FileChangeKind.MODIFIED, path="/foo/bar"
    )

    with self.assertRaises(pydantic.ValidationError):
      change.path = "/foo/baz"

    with self.assertRaises(pydantic.ValidationError):
      change.kind = triggers.FileChangeKind.DELETED


if __name__ == "__main__":
  unittest.main()
