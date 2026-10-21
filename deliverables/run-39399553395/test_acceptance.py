import unittest
import subprocess
import json
import tempfile
import os

B_RESULT_DIR = os.environ.get('B_RESULT_DIR', './')
csv_stats_path = os.path.join(B_RESULT_DIR, 'csv_stats.py')

class TestAcceptance(unittest.TestCase):
    def run_tool(self, csv_content):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            f.flush()
            result = subprocess.run(
                ['python', csv_stats_path, f.name],
                capture_output=True,
                text=True
            )
            os.unlink(f.name)
        return result

    def test_normal_case(self):
        csv_content = '''category,amount\n食品,100.00\n交通,100.25\n食品,50.00'''
        result = self.run_tool(csv_content)
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data['total_count'], 3)
        self.assertEqual(data['total_amount'], '250.25')
        self.assertIn('食品', data['category_stats'])
        self.assertIn('交通', data['category_stats'])

    def test_negative_amount(self):
        csv_content = '''category,amount\n食品,-50.00\n交通,100.25'''
        result = self.run_tool(csv_content)
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data['total_count'], 2)
        self.assertEqual(data['total_amount'], '50.25')
        self.assertEqual(data['category_stats']['食品']['amount'], '-50.00')

    def test_only_header(self):
        csv_content = '''category,amount'''
        result = self.run_tool(csv_content)
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data['total_count'], 0)
        self.assertEqual(data['total_amount'], '0.00')
        self.assertEqual(data['category_stats'], {})

    def test_missing_field(self):
        csv_content = '''category\n食品'''
        result = self.run_tool(csv_content)
        self.assertEqual(result.returncode, 1)
        self.assertIn("錯誤：CSV 檔案缺少必要欄位。", result.stderr)

    def test_empty_category(self):
        csv_content = '''category,amount\n食品,100.00\n,50.00'''
        result = self.run_tool(csv_content)
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIn('UNKNOWN', data['category_stats'])
        self.assertEqual(data['category_stats']['UNKNOWN']['amount'], '50.00')

    def test_invalid_amount(self):
        csv_content = '''category,amount\n食品,abc'''
        result = self.run_tool(csv_content)
        self.assertEqual(result.returncode, 1)
        self.assertIn("錯誤：金額格式無效。", result.stderr)

if __name__ == '__main__':
    unittest.main()
