import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault("ROLE", Path(__file__).resolve().parent.name[-1].upper())

import worker


class WorkerModelTests(unittest.TestCase):
    def test_rejects_added_requirements_outside_arbitration(self):
        self.assertTrue(worker.invents_unrequired_cases("需支援空檔案與多餘欄位"))
        self.assertFalse(worker.invents_unrequired_cases("核對正常、負金額與非法金額"))

    def test_detects_false_missing_spec_claims(self):
        self.assertTrue(worker.claims_missing_spec("找不到 SPEC.md 檔案"))
        self.assertTrue(worker.claims_missing_spec("SPEC.md 不存在"))
        self.assertFalse(worker.claims_missing_spec("已核對 SPEC.md 的輸出範例"))

    def test_spec_examples_are_parseable_and_cover_normal_input(self):
        invalid = ('```json\n{"total_count": int}\n```\n'
                   'category,amount\na,1.00\nb,2.00\nstderr 非零退出碼')
        self.assertIn('第 1 個 JSON 範例不可解析', worker.spec_problems(invalid))
        valid = ('category,amount\na,1.00\nb,2.00\n'
                 '```json\n{"total_count":2,"total_amount":"3.00","category_stats":{}}\n```\n'
                 'stderr 非零退出碼')
        self.assertEqual(worker.spec_problems(valid), [])

    def test_amendment_requires_concrete_feedback(self):
        payload = {"stage": "A_B", "feedback": "JSON 金額 Decimal 與錯誤行為"}
        self.assertFalse(worker.valid_proposal("交付範圍、驗收條件、依據資料", payload))
        self.assertFalse(worker.valid_proposal("足夠長的空泛內容" * 20, payload))
        complete = ('交付範圍：CSV 統計 CLI。驗收條件：Decimal 內部運算，JSON 金額為兩位小數字串，'
                    '只有標頭輸出 "0.00"；缺欄位及非法金額輸出明確錯誤並使用非零退出碼。'
                    '依據資料：category、amount 欄位；正常、負金額、空白分類等案例。')
        self.assertTrue(worker.valid_proposal(complete, payload))

    def test_falls_back_to_structured_response(self):
        with patch.object(worker, "model_once", side_effect=worker.ModelFormatError("bad format")), \
             patch.object(worker, "model_json_mode", return_value={"text": "criteria"}) as fallback:
            self.assertEqual(worker.model("prompt", ("text",)), {"text": "criteria"})
        fallback.assert_called_once_with("prompt", ("text",))

    def test_json_mode_uses_same_model_and_requires_fields(self):
        response = {"choices": [{"finish_reason": "stop", "message": {"content": '{"text":"criteria"}'}}]}
        with patch.dict(os.environ, {"MODEL_STUDIO_API_KEY": "dummy", "MODEL_STUDIO_BASE_URL": "https://example.invalid/v1"}), \
             patch.object(worker.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(response).encode())) as call:
            self.assertEqual(worker.model_json_mode("JSON prompt", ("text",)), {"text": "criteria"})
        request = call.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], "qwen3-coder-flash-2025-07-28")
        self.assertEqual(payload["response_format"], {"type": "json_object"})


if __name__ == "__main__":
    unittest.main()
