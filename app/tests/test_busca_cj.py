import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from busca_cj import main, normalize_page
from cj_client import CJClient, CJError


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 27, tzinfo=timezone.utc)
        self.data = {'pageSize': 3, 'pageNumber': 1, 'totalRecords': 6000, 'totalPages': 2000,
                     'content': [{'productList': [
                         {'id': 'p1', 'sku': 'spu', 'nameEn': 'Stand', 'sellPrice': '1.74 -- 3.33',
                          'warehouseInventoryNum': 60000, 'directMinOrderNum': None}]}]}

    def test_search_rows_remain_unapproved_and_price_range_is_only_hint(self):
        row = normalize_page(self.data, 'stand', now=self.now)['results'][0]
        self.assertEqual(row['product']['price_hint_unverified'], '1.74 -- 3.33')
        self.assertIsNone(row['price_floors'])
        self.assertEqual(row['status'], 'ANALISAR')
        self.assertFalse(row['publish_allowed'])
        self.assertFalse(row['purchase_allowed'])

    def test_bad_response_is_not_reported_as_empty_success(self):
        for data in (None, {}, {'content': [{}]}, {'content': [{'productList': [{}]}]}):
            with self.subTest(data=data), self.assertRaises(CJError):
                normalize_page(data, 'stand', now=self.now)

    def test_duplicate_product_is_not_counted_twice(self):
        self.data['content'][0]['productList'].append(self.data['content'][0]['productList'][0])
        self.assertEqual(len(normalize_page(self.data, 'stand', now=self.now)['results']), 1)

    def test_real_cli_flow_uses_client_and_saves_report(self):
        client = MagicMock()
        client.search.return_value = self.data
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'CJ_API_KEY': 'example'}), \
             patch('busca_cj.CJClient', return_value=client):
            output = Path(directory) / 'report.json'
            self.assertEqual(main(['stand', '--size', '3', '--output', str(output)]), 0)
            client.search.assert_called_once_with('stand', page=1, size=3)
            self.assertEqual(json.loads(output.read_text(encoding='utf-8'))['results'][0]['product']['pid'], 'p1')

    def test_invalid_search_does_not_contact_server(self):
        c = CJClient('key', lambda *args: self.fail('network called'))
        for keyword, page, size in [(' ', 1, 20), ('x', True, 20), ('x', 1, 0), ('x' * 201, 1, 20)]:
            with self.assertRaises(CJError):
                c.search(keyword, page, size)


if __name__ == '__main__':
    unittest.main()
