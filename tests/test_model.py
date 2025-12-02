
import ollama
import time

test_text = """

THE SKY ABOVE the port was the color of television, tuned to a dead channel.

“It’s not like I’m using,” Case heard someone say, as he shouldered his way through the crowd around the door of the Chat. “It’s like my body’s developed this massive drug deficiency.” It was a Sprawl voice and a Sprawl joke. The Chatsubo was a bar for professional expatriates; you could drink there for a week and never hear two words in Japanese.

Ratz was tending bar, his prosthetic arm jerking monotonously as he filled a tray of glasses with draft Kirin. He saw Case and smiled, his teeth a webwork of East European steel and brown decay. Case found a place at the bar, between the unlikely tan on one of Lonny Zone’s whores and the crisp naval uniform of a tall African whose cheekbones were ridged with precise rows of tribal scars. “Wage was in here early, with two joeboys,” Ratz said, shoving a draft across the bar with his good hand. “Maybe some business with you, Case?”

Case shrugged. The girl to his right giggled and nudged him.

The bartender’s smile widened. His ugliness was the stuff of legend. In an age of affordable beauty, there was something heraldic about his lack of it. The antique arm whined as he reached for another mug. It was a Russian military prosthesis, a seven-function force-feedback manipulator, cased in grubby pink plastic. “You are too much the artiste, Herr Case.” Ratz grunted; the sound served him as laughter. He scratched his overhang of white-shirted belly with the pink claw. “You are the artiste of the slightly funny deal.”

"""

# 定義你要 PK 的模型名稱 (請確保 ollama list 裡有這兩個名字)
models = ["gpt-oss:20b", "qwen3:14b", "gemma3:12b-it-qat"]

print(f"{'Model':<15} | {'Time(s)':<10} | {'Speed(T/s)':<12} | {'Translation Preview'}")
print("-" * 100)

for model in models:
    start_time = time.time()
    response = ""
    token_count = 0
    
    try:
        # 使用 stream 模式準確計算速度
        stream = ollama.chat(model=model, messages=[
            {'role': 'system', 'content': '你是專業翻譯，請將以下文字翻譯成流暢的台灣繁體中文。'},
            {'role': 'user', 'content': test_text}
        ], stream=True)
        
        for chunk in stream:
            content = chunk['message']['content']
            response += content
            token_count += 1 # 粗略計算 chunk 數，或可用 len(content)
            
        end_time = time.time()
        duration = end_time - start_time
        speed = token_count / duration
        
        # 擷取前 30 個字預覽
        preview = response.replace('\n', '')[:30] + "..."
        
        print(f"{model:<15} | {duration:<10.2f} | {speed:<12.2f} | {preview}")
        
        # 完整輸出存檔以便比對 (可選)
        with open(f"translation_{model.replace(':','_')}.txt", "w", encoding="utf-8") as f:
            f.write(response)
            
    except Exception as e:
        print(f"{model:<15} | FAILED: {e}")

print("-" * 100)
print("測試完成。請查看生成的 txt 檔對比詳細語意差異。")