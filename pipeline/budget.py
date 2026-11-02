import json
import math
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path


PRICES = {
    'claude-haiku-5-5': (0.10, 0.50),
    'claude-opus-5-5': (4.00, 20.00),
}


class Budget:
    def __init__(self, path: Path, ceiling_usd: float):
        if not math.isfinite(ceiling_usd) or ceiling_usd < 0:
            raise ValueError('ceiling must be finite and nonnegative')
        self.path = path
        self.ceiling_usd = ceiling_usd
        self._lock = threading.Lock()

    def record(self, model: str, input_tokens: int, output_tokens: int, *, batch: bool = False) -> None:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError('token counts must be nonnegative')
        input_price, output_price = PRICES[model]
        cost = (input_tokens * input_price + output_tokens * output_price) / 1_000_000
        if batch:
            cost /= 2
        with self._lock:
            spend = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
            month = datetime.now(timezone.utc).strftime('%Y-%m')
            spend[month] = spend.get(month, 0.0) + cost
            usage = spend.setdefault('usage', {}).setdefault(month, {}).setdefault(
                model, {'input_tokens': 0, 'output_tokens': 0},
            )
            usage['input_tokens'] += input_tokens
            usage['output_tokens'] += output_tokens
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, name = tempfile.mkstemp(dir=self.path.parent, prefix='.tmp-')
            os.close(descriptor)
            temporary = Path(name)
            try:
                temporary.write_text(
                    json.dumps(spend, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8',
                )
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)

    def month_spend_usd(self, month: str | None = None) -> float:
        month = month or datetime.now(timezone.utc).strftime('%Y-%m')
        spend = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
        return float(spend.get(month, 0.0))

    def over_ceiling(self) -> bool:
        return self.month_spend_usd() > self.ceiling_usd

    def usage(self, month: str | None = None) -> dict[str, dict[str, int]]:
        month = month or datetime.now(timezone.utc).strftime('%Y-%m')
        spend = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
        return spend.get('usage', {}).get(month, {})
