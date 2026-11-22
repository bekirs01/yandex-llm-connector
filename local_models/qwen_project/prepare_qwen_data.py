"""Подготовка обучающих примеров Qwen из исходных диалогов без изменения разметки."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
INPUT_FILE = ROOT / "autoservice_dataset" / "train.jsonl"
OUTPUT_FILE = ROOT / "prepared_data" / "qwen3.5-0.8b" / "train_sft.jsonl"

SYSTEM_INSTRUCTION = (
    "Ты извлекаешь структурированные сведения из русскоязычного диалога "
    "владельца автомобиля с помощником автосервиса. "
    "После указанной реплики верни только JSON с двумя полями: "
    "slots_after_message и evidence. "
    "slots_after_message — накопительное состояние слотов, значения — строки. "
    "evidence — только новые или изменённые сведения текущей реплики. "
    "Каждая запись evidence содержит ровно поля: slot, message_id, raw_text, "
    "kind, time_scope, supersedes, interpretation. "
    "raw_text — дословная цитата из текущего сообщения пользователя. "
    "Не считай вопросы и слова помощника новыми фактами пользователя. "
    "После реплики помощника состояние слотов не изменяется, evidence = []. "
    "Различай наблюдение, предположение, чужой диагноз и заказ услуги; "
    "не придумывай фактов. "
    "Используй значения слотов и идентификаторы услуг исходной схемы. "
    "Для исправления значения указывай в supersedes идентификатор "
    "предыдущей пользовательской реплики, служившей источником. "
    "Не добавляй других полей и пояснений."
)

EVIDENCE_KEYS = {
    "slot", "message_id", "raw_text", "kind", "time_scope", "supersedes", "interpretation"
}
TURN_KEYS = {"message_id", "role", "text", "slots_after_message", "evidence"}


def make_source(history: list[dict]) -> str:
    lines = ["Диалог до текущей реплики включительно:"]
    for turn in history:
        who = "Клиент" if turn["role"] == "user" else "Помощник"
        lines.append(f"{turn['message_id']} | {who}: {turn['text']}")
    lines.append(
        "Верни JSON с состоянием слотов после последней реплики "
        "и evidence только из последней реплики."
    )
    return "\n".join(lines)


def validate_turn(turn: dict, previous_state: dict, source_by_slot: dict) -> None:
    if set(turn) != TURN_KEYS:
        raise ValueError(f"Неверные поля реплики {turn.get('message_id')}")
    if turn["role"] not in {"user", "assistant"}:
        raise ValueError("Неизвестная роль")
    if not isinstance(turn["slots_after_message"], dict):
        raise ValueError("slots_after_message должен быть объектом")
    if not isinstance(turn["evidence"], list):
        raise ValueError("evidence должен быть списком")

    changes = {}
    for ev in turn["evidence"]:
        if not isinstance(ev, dict) or set(ev) != EVIDENCE_KEYS:
            raise ValueError("Неверные поля evidence")
        if ev["message_id"] != turn["message_id"]:
            raise ValueError("Некорректный message_id в evidence")
        if not isinstance(ev["raw_text"], str) or ev["raw_text"] not in turn["text"]:
            raise ValueError("raw_text не является дословной цитатой")
        slot, value = ev["slot"], ev["interpretation"]
        if slot in changes:
            raise ValueError("Повторное обновление одного слота")
        if ev["supersedes"] != source_by_slot.get(slot):
            raise ValueError("Неверный supersedes")
        changes[slot] = value

    if turn["role"] == "assistant" and turn["evidence"]:
        raise ValueError("Реплика помощника не должна создавать evidence")
    updated = dict(previous_state)
    updated.update(changes)
    if updated != turn["slots_after_message"]:
        raise ValueError("Состояние слотов не соответствует evidence")
    for slot in changes:
        source_by_slot[slot] = turn["message_id"]


def main() -> None:
    if not INPUT_FILE.is_file():
        raise FileNotFoundError(f"Не найден файл: {INPUT_FILE}")
    if (ROOT / "autoservice_dataset" / "test.jsonl").is_file():
        print("Тестовый набор найден; он не будет прочитан или изменён.")

    dialogues = 0
    examples = 0
    evidence_count = 0
    first_evidence_example = None
    seen_ids = set()

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Replace only the generated training artifact, never source data.
    with INPUT_FILE.open("r", encoding="utf-8") as source, OUTPUT_FILE.open(
        "w", encoding="utf-8"
    ) as output:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            dialogue = json.loads(line)
            dialogue_id = dialogue["dialogue_id"]
            if dialogue_id in seen_ids or dialogue["language"] != "ru":
                raise ValueError(f"Повтор ID или язык в строке {line_number}")
            seen_ids.add(dialogue_id)
            dialogues += 1

            history = []
            state = {}
            source_by_slot = {}
            for turn in dialogue["turns"]:
                validate_turn(turn, state, source_by_slot)
                history.append(turn)
                target = {
                    "slots_after_message": turn["slots_after_message"],
                    "evidence": turn["evidence"],
                }
                record = {
                    "messages": [
                        {"role": "system", "content": SYSTEM_INSTRUCTION},
                        {"role": "user", "content": make_source(history)},
                        {
                            "role": "assistant",
                            "content": json.dumps(target, ensure_ascii=False, separators=(",", ":")),
                        },
                    ]
                }
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                examples += 1
                evidence_count += len(turn["evidence"])
                if first_evidence_example is None and turn["evidence"]:
                    first_evidence_example = target
                state = dict(turn["slots_after_message"])

    if dialogues != 1000 or examples != 5681:
        raise ValueError(f"Неожиданный объём: {dialogues} диалогов, {examples} реплик")
    print("Подготовка завершена.")
    print(f"Обучающие диалоги: {dialogues}")
    print(f"Обучающие реплики: {examples}")
    print(f"Записи evidence: {evidence_count}")
    print(f"Файл: {OUTPUT_FILE}")
    print("Поля ответа: slots_after_message, evidence")
    print("Тестовый набор не использовался.")
    print("Пример ответа с evidence:")
    print(json.dumps(first_evidence_example, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
