from __future__ import annotations

import unittest

from wiicon5.conversation.context import ConversationContext, ResolvedEntity
from wiicon5.execution.artifacts import Artifact


class ConversationContextTests(unittest.TestCase):
    def test_context_keeps_messages_entities_and_artifacts(self) -> None:
        context = ConversationContext(session_id="s1", config_fingerprint="cfg_test")
        context.append_message("user", "Найди товар ABC-123")
        context.add_resolved_entity(
            ResolvedEntity(
                role="product",
                artifact_type="ProductRef",
                value={"ref": "product-1"},
                source="message:1",
            )
        )
        context.add_artifact(
            Artifact(
                name="product",
                type="ProductRef",
                value={"ref": "product-1"},
                provenance=["message:1"],
            )
        )

        self.assertEqual(context.latest_entity("product").value["ref"], "product-1")  # type: ignore[union-attr]
        self.assertEqual(context.latest_artifact("ProductRef").value["ref"], "product-1")  # type: ignore[union-attr]
        packet = context.to_packet()
        self.assertEqual(packet["config_fingerprint"], "cfg_test")
        self.assertEqual(packet["messages"][0]["content"], "Найди товар ABC-123")


if __name__ == "__main__":
    unittest.main()

