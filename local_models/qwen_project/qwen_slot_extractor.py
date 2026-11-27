r"""Load the project's trained Qwen LoRA and inspect one held-out prediction.

Place beside prepare_qwen_data.py in autoservice_slot_training, then run:
    .\.venv_qwen\Scripts\python.exe -X utf8 .\qwen_slot_extractor.py --demo

For application use: QwenSlotExtractor(project_root).extract(history).
History items contain message_id, role (user/assistant), and text only.
This file never trains, downloads weights, or changes the dataset/model files.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import lru_cache
import json
import os
from pathlib import Path
import runpy
import sys
import time


ROOT = Path(__file__).resolve().parent
LORA_TARGETS = ["q_proj", "v_proj", "in_proj_qkv"]
EVIDENCE_FIELDS = {
    "slot", "message_id", "raw_text", "kind", "time_scope",
    "supersedes", "interpretation",
}
KINDS = {"observation", "hypothesis", "reported_diagnosis", "service_request"}
TIME_SCOPES = {"past", "current", "unspecified"}


def clean_history(history: list[dict]) -> list[dict]:
    """Drop annotations: gold slots/evidence must never enter the model prompt."""
    if not isinstance(history, list) or not history:
        raise ValueError("Konusma gecmisi bos olmayan bir liste olmali.")
    cleaned, seen = [], set()
    for turn in history:
        if not isinstance(turn, dict):
            raise ValueError("Her mesaj bir JSON nesnesi olmali.")
        item = {key: turn.get(key) for key in ("message_id", "role", "text")}
        if any(not isinstance(value, str) or not value.strip() for value in item.values()):
            raise ValueError("Mesajda message_id, role ve text gerekli.")
        if item["role"] not in {"user", "assistant"}:
            raise ValueError("Mesaj rolu user veya assistant olmali.")
        if item["message_id"] in seen:
            raise ValueError(f"Tekrarlanan message_id: {item['message_id']}")
        seen.add(item["message_id"])
        cleaned.append(item)
    return cleaned


@lru_cache(maxsize=4)
def _prompt_helpers(project_root: Path):
    # __name__ is <run_path>, so the data-preparation main() is not called.
    module = runpy.run_path(str(project_root / "prepare_qwen_data.py"))
    return module["SYSTEM_INSTRUCTION"], module["make_source"]


def prompt_messages(history: list[dict], project_root: Path = ROOT) -> list[dict]:
    # Reuse the actual training prompt, including its accumulated-state rules.
    instruction, make_source = _prompt_helpers(Path(project_root).resolve())
    return [
        {"role": "system", "content": instruction},
        {"role": "user", "content": make_source(clean_history(history))},
    ]


def add_classifier_proposals(messages, classifier_proposals):
    if classifier_proposals is not None:
        messages[0]["content"] += (
            "\nПредложения классификатора приведены после диалога. "
            "Проверь их по словам клиента и приводи только дословные цитаты."
        )
        messages[1]["content"] += "\nПредложения классификатора: " + classifier_proposals



def inspect_artifacts(project_root: Path) -> tuple[Path, Path, dict]:
    base = project_root / "models/qwen3.5-0.8b"
    adapter = project_root / "trained_model/qwen3.5-0.8b-lora"
    required = [
        project_root / "prepare_qwen_data.py",
        base / "config.json",
        adapter / "training_info.json",
        adapter / "lora_weights.safetensors",
        adapter / "tokenizer_config.json",
        adapter / "tokenizer.json",
    ]
    missing = [str(path) for path in required if not path.is_file() or not path.stat().st_size]
    if missing:
        raise FileNotFoundError("Eksik/bos dosyalar:\n" + "\n".join(missing))

    index = base / "model.safetensors.index.json"
    if index.is_file():
        weight_map = json.loads(index.read_text(encoding="utf-8"))["weight_map"]
        if not isinstance(weight_map, dict) or not weight_map:
            raise ValueError("Temel modelin agirlik indeksi bos veya gecersiz.")
        weight_names = set(weight_map.values())
        if any(not isinstance(name, str) or Path(name).name != name for name in weight_names):
            raise ValueError("Temel modelin agirlik indeksinde gecersiz dosya adi.")
        weights = [base / name for name in weight_names]
    else:
        weights = list(base.glob("*.safetensors"))
    if not weights or any(not path.is_file() or not path.stat().st_size for path in weights):
        raise FileNotFoundError(f"Temel model agirliklari eksik: {base}")

    info = json.loads((adapter / "training_info.json").read_text(encoding="utf-8"))
    expected = {
        "schema_version": 1, "lora_r": 4, "lora_alpha": 8,
        "lora_dropout": 0.0, "lora_targets": LORA_TARGETS,
        "target_fields": ["slots_after_message", "evidence"],
    }
    if any(info.get(key) != value for key, value in expected.items()):
        raise ValueError("LoRA ayarlari beklenen egitim yapisiyla eslesmiyor.")
    if type(info.get("trained_steps")) is not int or info["trained_steps"] <= 0:
        raise ValueError("training_info.json icinde gecerli trained_steps yok.")
    if type(info.get("max_tokens")) is not int or info["max_tokens"] <= 0:
        raise ValueError("training_info.json icinde gecerli max_tokens yok.")
    # base_model_dir in this metadata is a Colab path. Resolve Windows paths
    # from project_root instead; never load a model from that recorded path.
    return base, adapter, info


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Tekrarlanan JSON anahtari: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"Gecersiz JSON sayisi: {value}")


def parse_prediction(raw: str, history: list[dict]) -> tuple[dict | None, list[str]]:
    """Validate structure and evidence grounding; this is not a quality score."""
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except ValueError as exc:
        return None, [f"JSON okunamadi: {exc}"]
    if not isinstance(value, dict) or set(value) != {"slots_after_message", "evidence"}:
        return None, ["Ciktida yalnizca slots_after_message ve evidence olmali."]
    slots, evidence = value["slots_after_message"], value["evidence"]
    if not isinstance(slots, dict) or any(
        not isinstance(key, str) or not key or not isinstance(item, str)
        for key, item in slots.items()
    ):
        return value, ["Slot adlari ve degerleri metin olmali."]
    if not isinstance(evidence, list):
        return value, ["evidence bir liste olmali."]

    current = history[-1]
    prior_users = {turn["message_id"] for turn in history[:-1] if turn["role"] == "user"}
    errors, seen_slots = [], set()
    if current["role"] == "assistant" and evidence:
        errors.append("Asistan mesaji yeni evidence olusturmamali.")
    for number, entry in enumerate(evidence, 1):
        prefix = f"evidence[{number}]"
        if not isinstance(entry, dict) or set(entry) != EVIDENCE_FIELDS:
            errors.append(f"{prefix}: alanlar egitim semasiyla eslesmiyor.")
            continue
        string_fields = EVIDENCE_FIELDS - {"supersedes"}
        if any(not isinstance(entry[key], str) for key in string_fields):
            errors.append(f"{prefix}: supersedes disindaki alanlar metin olmali.")
            continue
        if entry["kind"] not in KINDS or entry["time_scope"] not in TIME_SCOPES:
            errors.append(f"{prefix}: gecersiz kind/time_scope.")
        if entry["message_id"] != current["message_id"]:
            errors.append(f"{prefix}: message_id son mesaja ait degil.")
        if not entry["raw_text"] or entry["raw_text"] not in current["text"]:
            errors.append(f"{prefix}: raw_text son mesajdan birebir alinti degil.")
        supersedes = entry["supersedes"]
        if supersedes is not None and (
            not isinstance(supersedes, str) or supersedes not in prior_users
        ):
            errors.append(f"{prefix}: supersedes onceki bir kullanici mesajina ait degil.")
        slot = entry["slot"]
        if slot in seen_slots:
            errors.append(f"{prefix}: ayni slot icin birden fazla guncelleme.")
        seen_slots.add(slot)
        if slot not in slots or slots[slot] != entry["interpretation"]:
            errors.append(f"{prefix}: interpretation, slot degeriyle eslesmiyor.")
    return value, errors


@dataclass
class Prediction:
    raw: str
    value: dict | None
    errors: list[str]
    seconds: float
    generated_tokens: int


class QwenSlotExtractor:
    """Keep one instance alive and call extract(history) for each new turn."""

    def __init__(self, project_root: Path | str = ROOT, device: str = "auto"):
        project_root = Path(project_root).resolve()
        self.project_root = project_root
        base, adapter, self.info = inspect_artifacts(project_root)
        try:
            import torch
            from peft import LoraConfig
            from safetensors.torch import load_file
            from transformers import AutoModelForMultimodalLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "Egitimde kullandiginiz .venv_qwen Python ortamini kullanin. "
                f"Import hatasi: {exc}"
            ) from exc

        if device == "auto":
            if torch.cuda.is_available():
                device = "cuda:0"
            elif torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"
        if device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA kullanilamiyor; --device cpu secilebilir.")
        if device == "mps" and not torch.backends.mps.is_available():
            raise RuntimeError("MPS kullanilamiyor; --device cpu secilebilir.")
        self.torch, self.device = torch, torch.device(device)
        if self.device.type == "cpu":
            torch.set_num_threads(min(4, os.cpu_count() or 4))
        print(f"Device: {self.device}; trained steps: {self.info['trained_steps']}", flush=True)
        print("Temel model yukleniyor...", flush=True)
        self.tokenizer = AutoTokenizer.from_pretrained(str(adapter), local_files_only=True)
        if self.tokenizer.eos_token_id is None:
            raise ValueError("Tokenizer EOS tokeni tanimli degil.")
        # The checkpoint is stored as BF16. MPS has no reliable device_map target.
        weight_dtype = torch.bfloat16 if self.device.type == "mps" else torch.float32
        if self.device.type == "mps":
            self.model = AutoModelForMultimodalLM.from_pretrained(
                str(base), dtype=weight_dtype, low_cpu_mem_usage=True, local_files_only=True,
            )
            self.model.to(self.device)
        else:
            self.model = AutoModelForMultimodalLM.from_pretrained(
                str(base), dtype=weight_dtype, device_map=str(self.device),
                low_cpu_mem_usage=True, local_files_only=True,
            )
        try:
            self.model.add_adapter(LoraConfig(
                r=self.info["lora_r"], lora_alpha=self.info["lora_alpha"],
                lora_dropout=self.info["lora_dropout"], bias="none",
                target_modules=self.info["lora_targets"],
            ))
        except ImportError as exc:
            if "torchao" in str(exc).lower():
                raise RuntimeError(
                    "Kullanilmayan torchao paketi PEFT ile uyumsuz. Ayni Python "
                    "ortaminda -m pip uninstall -y torchao calistirip yeniden deneyin."
                ) from exc
            raise
        current = {name: parameter for name, parameter in self.model.named_parameters()
                   if parameter.requires_grad}
        if not current or any("lora_" not in name for name in current):
            raise RuntimeError("Beklenen LoRA parametreleri olusturulamadi.")
        stored = load_file(str(adapter / "lora_weights.safetensors"), device="cpu")
        if set(current) != set(stored):
            missing, extra = sorted(set(current) - set(stored)), sorted(set(stored) - set(current))
            raise RuntimeError(f"LoRA parametre adlari uyumsuz: missing={missing[:5]}, extra={extra[:5]}")
        with torch.no_grad():
            for name, parameter in current.items():
                source = stored[name]
                if parameter.shape != source.shape:
                    raise RuntimeError(f"LoRA boyut uyumsuz: {name}")
                if parameter.dtype != source.dtype:
                    source = source.to(dtype=parameter.dtype)
                parameter.copy_(source)
        del stored
        self.model.eval()
        self.model.requires_grad_(False)
        self.model.config.use_cache = True
        print(f"BASE_AND_LORA_LOADED ({len(current)} tensors)", flush=True)

    def generate(self, history: list[dict], max_new_tokens: int = 1024, *, classifier_proposals: str | None = None, should_stop=None) -> Prediction:
        if type(max_new_tokens) is not int or not 1 <= max_new_tokens <= 4096:
            raise ValueError("max_new_tokens 1 ile 4096 arasinda olmali.")
        history = clean_history(history)
        messages = prompt_messages(history, self.project_root)
        add_classifier_proposals(messages, classifier_proposals)
        raw, elapsed, count, truncated, cancelled = self.generate_text(
            messages, max_new_tokens, should_stop,
        )
        if cancelled:
            return Prediction(raw, None, ["cancelled"], elapsed, count)
        value, errors = parse_prediction(raw, history)
        if truncated:
            errors.append("Cikti token sinirina ulasti.")
        return Prediction(raw, value, errors, elapsed, count)

    def generate_text(self, messages, max_new_tokens, should_stop=None):
        try:
            encoded = self.tokenizer.apply_chat_template(
                messages, tokenize=True, add_generation_prompt=True, enable_thinking=False,
            )
        except TypeError:
            encoded = self.tokenizer.apply_chat_template(
                messages, tokenize=True, add_generation_prompt=True,
            )
        if hasattr(encoded, "keys"):
            encoded = encoded["input_ids"]
        if hasattr(encoded, "tolist"):
            encoded = encoded.tolist()
        if encoded and isinstance(encoded[0], list):
            if len(encoded) != 1:
                raise ValueError("Bir konusma bekleniyordu.")
            encoded = encoded[0]
        if not encoded or not all(isinstance(token, int) for token in encoded):
            raise ValueError("Tokenizer beklenmeyen token bicimi dondurdu.")
        if len(encoded) > self.info["max_tokens"]:
            raise ValueError("Konusma egitimdeki token sinirini asiyor; otomatik kirpilmadi.")
        torch = self.torch
        input_ids = torch.tensor([encoded], dtype=torch.long, device=self.device)
        started = time.perf_counter()
        cancelled = {"value": False}
        stopping = None
        if should_stop is not None:
            from transformers import StoppingCriteria, StoppingCriteriaList

            class _StopWhen(StoppingCriteria):
                def __call__(self, input_ids, scores, **kwargs):
                    if should_stop():
                        cancelled["value"] = True
                        return True
                    return False

            stopping = StoppingCriteriaList([_StopWhen()])
        with torch.inference_mode():
            output = self.model.generate(
                input_ids=input_ids, attention_mask=torch.ones_like(input_ids),
                max_new_tokens=max_new_tokens, do_sample=False, num_beams=1,
                eos_token_id=self.tokenizer.eos_token_id,
                pad_token_id=self.tokenizer.eos_token_id, use_cache=True,
                stopping_criteria=stopping,
            )
        new_tokens = output[0][input_ids.shape[1]:].tolist()
        raw = self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
        elapsed = time.perf_counter() - started
        truncated = (
            not cancelled["value"]
            and len(new_tokens) >= max_new_tokens
            and new_tokens[-1] != self.tokenizer.eos_token_id
        )
        return raw, elapsed, len(new_tokens), truncated, cancelled["value"]

    def draft_reply(self, transcript: str, max_new_tokens: int = 64) -> tuple[str, float, int]:
        """Short instruction draft from the base model, with the slot adapter off.

        This is for comparison only. The chat path does not call it.
        """

        if not isinstance(transcript, str) or not transcript.strip():
            raise ValueError("transcript must be text")
        messages = [
            {"role": "system", "content": (
                "Напиши один короткий естественный ответ клиенту автосервиса по-русски. "
                "Опирайся только на реплики клиента. Не выдумывай цену, мастерскую, время или запись. "
                "Если это приветствие или благодарность, ответь на это и не начинай анкету. "
                "Задай не больше одного вопроса."
            )},
            {"role": "user", "content": transcript.strip()},
        ]
        # The installed transformers build has no adapter-off context manager.
        # Zeroing the LoRA tensors uses the already loaded base weights.
        saved: list[tuple] = []
        try:
            with self.torch.no_grad():
                for name, param in self.model.named_parameters():
                    if "lora_" not in name:
                        continue
                    saved.append((param, param.detach().clone()))
                    param.zero_()
            if not saved:
                raise RuntimeError("base model adapter cannot be disabled")
            raw, elapsed, count, _truncated, cancelled = self.generate_text(messages, max_new_tokens)
        finally:
            with self.torch.no_grad():
                for param, value in saved:
                    param.copy_(value)
        if cancelled:
            raise RuntimeError("draft cancelled")
        return raw, elapsed, count

    def extract(self, history: list[dict], max_new_tokens: int = 1024) -> dict:
        """Return validated output; callers must handle an invalid prediction."""
        prediction = self.generate(history, max_new_tokens)
        if prediction.errors:
            raise ValueError("Gecersiz model ciktisi: " + "; ".join(prediction.errors))
        return prediction.value


def load_demo(test_path: Path, dialogue_id: str | None, message_id: str | None):
    with test_path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            record = json.loads(line)
            if dialogue_id is None or record["dialogue_id"] == dialogue_id:
                break
        else:
            raise ValueError("Istenen test diyalogu bulunamadi.")
    turns = record["turns"]
    selected = next((i for i, turn in enumerate(turns) if
                     (turn["message_id"] == message_id if message_id else turn["role"] == "user")), None)
    if selected is None:
        raise ValueError("Istenen test mesaji bulunamadi.")
    target = turns[selected]
    history = clean_history(turns[:selected + 1])
    expected = {key: target[key] for key in ("slots_after_message", "evidence")}
    return record["dialogue_id"], history, expected


def main() -> int:
    parser = argparse.ArgumentParser(description="Egitilmis Qwen LoRA yukleme ve ilk tahmin kontrolu")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--demo", action="store_true", help="Test setinden bir mesaj dene")
    action.add_argument("--history", type=Path, help="message_id/role/text mesaj listesini iceren JSON")
    action.add_argument("--check-files", action="store_true", help="Dosyalari kontrol et; modeli yukleme")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda:0", "mps"], default="auto")
    parser.add_argument("--dialogue-id")
    parser.add_argument("--message-id")
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    args = parser.parse_args()
    root = args.root.resolve()
    _, _, info = inspect_artifacts(root)
    print(f"FILES_OK; trained steps: {info['trained_steps']}", flush=True)
    if args.check_files:
        return 0
    expected = None
    if args.demo:
        dialogue_id, history, expected = load_demo(
            root / "autoservice_dataset/test.jsonl", args.dialogue_id, args.message_id,
        )
        print(f"Demo: {dialogue_id}, {history[-1]['message_id']}", flush=True)
    else:
        history = clean_history(json.loads(args.history.read_text(encoding="utf-8-sig")))
    print("KONUSMA:", flush=True)
    print(json.dumps(history, ensure_ascii=False, indent=2), flush=True)
    extractor = QwenSlotExtractor(root, args.device)
    print("Tahmin uretiliyor...", flush=True)
    prediction = extractor.generate(history, args.max_new_tokens)
    print("\nMODEL TAHMINI:")
    print(json.dumps(prediction.value, ensure_ascii=False, indent=2)
          if prediction.value is not None else prediction.raw)
    print(f"\nSure: {prediction.seconds:.1f} saniye; uretilen token: {prediction.generated_tokens}")
    if prediction.errors:
        print("OUTPUT_VALIDATION_FAILED:")
        for error in prediction.errors:
            print("-", error)
    else:
        print("JSON_AND_EVIDENCE_STRUCTURE_OK")
    if expected is not None:
        print("\nBEKLENEN CEVAP (TEST VERISI):")
        print(json.dumps(expected, ensure_ascii=False, indent=2))
        if prediction.value is not None:
            print("SLOTS_EXACT_MATCH:", prediction.value["slots_after_message"] == expected["slots_after_message"])
            canonical = lambda values: sorted(json.dumps(v, ensure_ascii=False, sort_keys=True) for v in values)
            # Evidence list order is irrelevant; every object's content must match.
            if isinstance(prediction.value["evidence"], list):
                print("EVIDENCE_EXACT_MATCH (order ignored):",
                      canonical(prediction.value["evidence"]) == canonical(expected["evidence"]))
        print("Bu tek mesajlik kontroldur; tum test setinin basari olcumu degildir.")
    return 2 if prediction.errors else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ImportError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        print(f"\nERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
