from __future__ import annotations

import unittest

from wiicon5.semantic_roles import canonical_role, roles_match


class SemanticRoleTests(unittest.TestCase):
    def test_entity_identity_suffixes_are_normalized_generically(self) -> None:
        self.assertEqual(canonical_role("warehouse_name"), "warehouse")
        self.assertEqual(canonical_role("customer_ref"), "customer")
        self.assertEqual(canonical_role("partner_reference"), "partner")
        self.assertEqual(canonical_role("склад_наименование"), "склад")
        self.assertTrue(roles_match("warehouse_name", "warehouse"))

    def test_explicit_business_alias_wins_before_generic_suffix(self) -> None:
        self.assertEqual(canonical_role("price_type_name"), "price_type")
        self.assertEqual(canonical_role("product_name"), "product")


if __name__ == "__main__":
    unittest.main()
