import os
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat
from dotenv import load_dotenv

# 加载 .env 环境变量
load_dotenv()

async def main():
    print("=" * 50)
    print(" 📡 Gatekeeper: TG Channel Explorer ")
    print("=" * 50)
    
    # 尝试从环境变量获取，如果没有则提示用户输入
    api_id_str = os.getenv("TG_API_ID")
    api_hash = os.getenv("TG_API_HASH")
    
    if not api_id_str or not api_hash:
        print("\n⚠️ 缺少 TG_API_ID 或 TG_API_HASH。")
        print("请前往 https://my.telegram.org/apps 申请 API 凭证。\n")
        api_id_str = input("请输入您的 API ID: ").strip()
        api_hash = input("请输入您的 API HASH: ").strip()
        
        # 可选：将输入的凭证保存到 .env 方便下次使用
        save = input("是否将凭证保存到 .env 文件中？(y/n) [y]: ").strip().lower()
        if save != 'n':
            with open(".env", "a") as f:
                f.write(f"\nTG_API_ID={api_id_str}\nTG_API_HASH={api_hash}\n")
            print("✅ 已保存到 .env 文件。")

    try:
        api_id = int(api_id_str)
    except ValueError:
        print("❌ API ID 必须是数字！")
        return

    print("\n⏳ 正在连接到 Telegram (如果是首次登录，将要求输入手机号和验证码)...")
    
    # 使用会话文件 'session_gatekeeper' 保存登录状态
    client = TelegramClient('session_gatekeeper', api_id, api_hash)
    await client.start()
    
    print("\n✅ 登录成功！正在获取您所在的频道和群组列表...\n")
    print(f"{'Name':<40} | {'ID':<15} | {'Type'}")
    print("-" * 70)
    
    # 遍历所有对话
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        dialog_type = "Unknown"
        
        if isinstance(entity, Channel):
            if getattr(entity, 'megagroup', False):
                dialog_type = "Group (Supergroup)"
            elif getattr(entity, 'broadcast', False):
                dialog_type = "Channel"
        elif isinstance(entity, Chat):
            dialog_type = "Group"
        else:
            continue # 跳过私人对话 (User)
            
        name = dialog.name
        # 为了美观截断过长的名字
        if len(name) > 38:
            name = name[:35] + "..."
            
        print(f"{name:<40} | {dialog.id:<15} | {dialog_type}")
        
    print("\n" + "=" * 50)
    print("💡 请记录下您想要监听的 频道/群组 的 ID。")
    print("稍后我们将把这些 ID 填入 Fetcher 监控程序的白名单中。")

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
