import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault("ROLE", Path(__file__).resolve().parent.name[-1].upper())

import worker


class WorkerModelTests(unittest.TestCase):
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
