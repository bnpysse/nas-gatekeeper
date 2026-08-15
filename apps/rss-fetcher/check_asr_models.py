#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
每日 ASR 模型健康检查与排序脚本
测试各个模型是否可用，并将可用的模型以优先级顺序写入 working_asr_models.json
"""

import os
import time
import json
import urllib.request
from http import HTTPStatus
from dashscope.audio.asr import Transcription
import dashscope
from dotenv import load_dotenv

# 加载环境变量
script_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(script_dir, '.env'))
dashscope.api_key = os.getenv('DASHSCOPE_API_KEY')

if not dashscope.api_key:
    print("Error: DASHSCOPE_API_KEY not found in environment.")
    exit(1)

# 按优先级顺序排列待测试的模型
MODELS_TO_TEST = ['paraformer-v2', 'paraformer-v1', 'sensevoice-v1']
OUTPUT_FILE = os.path.join(script_dir, 'working_asr_models.json')
TEST_AUDIO_URL = "https://dashscope.oss-cn-beijing.aliyuncs.com/samples/audio/sensevoice/rich_text_example_1.wav"

def check_model(model_name: str) -> bool:
    print(f"[{model_name}] 🚀 开始测试...")
    try:
        task_response = Transcription.async_call(
            model=model_name,
            file_urls=[TEST_AUDIO_URL],
            language_hints=['zh', 'en']
        )
        
        if task_response.status_code == HTTPStatus.OK:
            transcribe_response = Transcription.wait(task=task_response.output.task_id)
            if transcribe_response.status_code == HTTPStatus.OK:
                # 检查 results 中是否含有 subtask_status 为 SUCCEEDED 或者有实际内容
                results = transcribe_response.output.get("results", [])
                if results and results[0].get("subtask_status") == "SUCCEEDED":
                    print(f"[{model_name}] ✅ 测试通过！")
                    return True
                else:
                    print(f"[{model_name}] ❌ 识别失败，状态: {results[0].get('subtask_status') if results else '未知'}")
                    return False
            else:
                print(f"[{model_name}] ❌ 轮询失败: {transcribe_response.message}")
                return False
        else:
            print(f"[{model_name}] ❌ 提交失败: {task_response.message}")
            return False
    except Exception as e:
        print(f"[{model_name}] ❌ 发生异常: {str(e)}")
        return False

def main():
    working_models = []
    print("🔍 正在检查 ASR 模型可用性...")
    for model in MODELS_TO_TEST:
        if check_model(model):
            working_models.append(model)
        time.sleep(1) # 稍微暂停防止并发限制
        
    print(f"\n✅ 可用模型列表: {working_models}")
    
    # 始终保存至少一个模型（即便测试偶发失败，Fallback 也是有必要的，但为了安全我们只记录 working_models，如果全挂就用默认）
    if not working_models:
        print("⚠️ 警告：所有模型测试均失败，将使用默认 fallback 配置！")
        working_models = MODELS_TO_TEST
        
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(working_models, f, indent=4)
        
    print(f"💾 已将可用模型保存至 {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
