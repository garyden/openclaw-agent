import os
import json
from openai import OpenAI

client = None


def get_client():
    global client
    if client is None:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise ValueError("OPENAI_API_KEY is required for AI intent parsing")
        client = OpenAI(api_key=key)
    return client

SYSTEM_PROMPT = """
你是一个房地产 Telegram bot 的意图解析器。
你的任务不是聊天，而是把用户输入转换成结构化 JSON。

请严格只返回 JSON，不要加解释，不要加 markdown，不要加代码块。

支持的 intent:
- analyze_property
- update_property
- delete_property
- compare_properties
- find_best_property
- remember_fact
- remember_preference
- show_memory
- unknown

JSON 格式如下：
{
  "intent": "update_property",
  "address": "",
  "fields": {},
  "raw_text": ""
}

规则：
1. 如果用户要分析房产，intent = analyze_property
2. 如果用户要修改房产信息，intent = update_property
3. 如果用户要删除房产，intent = delete_property
4. 如果用户要比较房产，intent = compare_properties
5. 如果用户要找最值得投资/现金流最好的房产，intent = find_best_property
6. 如果用户要“记住”一个事实，intent = remember_fact
7. 如果用户要“记住”一个偏好，例如“我喜欢...”，intent = remember_preference
8. 如果用户要查看记忆，intent = show_memory
9. 如果无法判断，intent = unknown

字段提取要求：
- address: 尽量提取房产地址或房产标识；没有就返回空字符串
- fields: 只放用户明确要求修改的字段，例如:
  {
    "rent": 2800,
    "down_payment": 25,
    "interest_rate": 6.5
  }
- raw_text: 原始用户输入
"""

def parse_user_intent(user_text: str) -> dict:
    response = get_client().responses.create(
        model="gpt-5.4",
        instructions=SYSTEM_PROMPT,
        input=user_text,
    )

    text = response.output_text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = {
            "intent": "unknown",
            "address": "",
            "fields": {},
            "raw_text": user_text,
            "error": "model_did_not_return_valid_json",
            "model_output": text,
        }

    if "intent" not in data:
        data["intent"] = "unknown"
    if "address" not in data:
        data["address"] = ""
    if "fields" not in data or not isinstance(data["fields"], dict):
        data["fields"] = {}
    if "raw_text" not in data:
        data["raw_text"] = user_text

    return data


if __name__ == "__main__":
    while True:
        text = input("你: ").strip()
        if text.lower() in {"exit", "quit"}:
            break
        result = parse_user_intent(text)
        print(json.dumps(result, ensure_ascii=False, indent=2))
