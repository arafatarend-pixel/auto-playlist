import requests
import re
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

MAIN_M3U = 'Playlist.m3u'
URLS_FILE = 'urls.txt'

# কতগুলো থ্রেড দিয়ে লিংক চেক করবে (অনেক বেশি দিলে রেট লিমিট হতে পারে)
MAX_WORKERS = 15
# লিংক চেক করার টাইমআউট (সেকেন্ড)
CHECK_TIMEOUT = 8


def fetch_m3u(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Failed to fetch {url}: {e}")
        return ""


def normalize_name(name):
    """চ্যানেল নাম পরিষ্কার করে ম্যাচিংয়ের জন্য"""
    name = name.lower().strip()
    
    # সাধারণ কোয়ালিটি সাফিক্স সরানো
    name = re.sub(r'\b(hd|fhd|uhd|4k|8k|hevc|h265|h264)\b', '', name)
    
    # স্পেশাল ক্যারেক্টার, ইমোজি, পাইপ ইত্যাদি সরানো
    name = re.sub(r'[┃\|\[\]\(\)\{\}•·►◄»«]', '', name)
    name = re.sub(r'[^\w\s]', ' ', name)  # বাকি স্পেশাল ক্যারেক্টার স্পেস দিয়ে রিপ্লেস
    
    # অতিরিক্ত স্পেস সরানো
    name = re.sub(r'\s+', ' ', name).strip()
    
    return name


def parse_m3u(text):
    channels = []
    lines = text.strip().split('\n')
    for i in range(len(lines)):
        line = lines[i].strip()
        if line.startswith('#EXTINF:'):
            info_line = line
            url_line = ""
            for j in range(i+1, len(lines)):
                if lines[j].strip() and not lines[j].strip().startswith('#'):
                    url_line = lines[j].strip()
                    break
            
            original_name = info_line.split(',')[-1].strip()
            name = normalize_name(original_name)
            
            group_match = re.search(r'group-title="([^"]*)"', info_line)
            group = group_match.group(1) if group_match else "Uncategorized"
            
            channels.append({
                'name': name,
                'original_name': original_name,
                'group': group,
                'info': info_line,
                'url': url_line
            })
    return channels


def is_url_alive(url):
    """
    স্ট্রিম লিংক সচল কিনা চেক করে।
    HEAD চেষ্টা করে, ব্যর্থ হলে ছোট GET করে।
    """
    if not url or not url.startswith(('http://', 'https://')):
        return False

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': '*/*',
        'Connection': 'close'
    }

    try:
        # প্রথমে HEAD চেষ্টা
        resp = requests.head(url, headers=headers, timeout=CHECK_TIMEOUT, allow_redirects=True)
        if resp.status_code in (200, 206, 301, 302, 307, 308):
            return True
        # কিছু সার্ভার HEAD সাপোর্ট করে না
        if resp.status_code in (403, 405, 501):
            pass  # GET এ যাবো
        else:
            return False
    except Exception:
        pass

    # HEAD ব্যর্থ হলে ছোট GET (শুধু প্রথম কয়েক বাইট)
    try:
        headers['Range'] = 'bytes=0-1023'
        resp = requests.get(url, headers=headers, timeout=CHECK_TIMEOUT, allow_redirects=True, stream=True)
        if resp.status_code in (200, 206):
            # একটু কনটেন্ট আছে কিনা দেখি
            content = next(resp.iter_content(512), b'')
            resp.close()
            return len(content) > 0
        return False
    except Exception:
        return False


def find_working_url(channel_name, backup_candidates):
    """
    ব্যাকআপ ক্যান্ডিডেট লিস্ট থেকে প্রথম সচল লিংক খুঁজে দেয়।
    backup_candidates = list of urls (order = priority)
    """
    for url in backup_candidates:
        if is_url_alive(url):
            return url
    return None


def main():
    if not os.path.exists(URLS_FILE) or not os.path.exists(MAIN_M3U):
        print("Required files not found!")
        return
        
    with open(URLS_FILE, 'r', encoding='utf-8') as f:
        urls = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
    
    if len(urls) < 2:
        print("Not enough URLs in urls.txt")
        return

    # শেষের অংশকে স্পোর্টস ধরা হচ্ছে
    sports_count = 2   # ← এখানে কতগুলো স্পোর্টস সোর্স আছে সেটা লিখো
    backup_urls = urls[:-sports_count] if len(urls) > sports_count else []
    sports_urls = urls[-sports_count:] if len(urls) >= sports_count else urls

    with open(MAIN_M3U, 'r', encoding='utf-8') as f:
        main_text = f.read()
    
    main_channels = parse_m3u(main_text)

    # ========== ব্যাকআপ থেকে সব সম্ভাব্য লিংক সংগ্রহ ==========
    # name -> list of urls (priority order অনুযায়ী)
    backup_candidates = {}
    for b_url in backup_urls:
        print(f"Fetching backup: {b_url}")
        b_text = fetch_m3u(b_url)
        if b_text:
            b_channels = parse_m3u(b_text)
            for ch in b_channels:
                if ch['name'] not in backup_candidates:
                    backup_candidates[ch['name']] = []
                # ডুপ্লিকেট এড়ানো
                if ch['url'] not in backup_candidates[ch['name']]:
                    backup_candidates[ch['name']].append(ch['url'])

    # ========== লাইভ স্পোর্টস ফেচ ==========
    live_channels = []
    for s_url in sports_urls:
        print(f"Fetching sports: {s_url}")
        s_text = fetch_m3u(s_url)
        if s_text:
            s_channels = parse_m3u(s_text)
            live_channels.extend(s_channels)

    # ========== শুধু মৃত লিংকগুলো আপডেট ==========
    print("\nChecking which channels need update...")
    
    # প্রথমে কোন চ্যানেলগুলোর বর্তমান লিংক মৃত সেগুলো চিহ্নিত করি
    to_check = []
    for idx, ch in enumerate(main_channels):
        if ch['group'] == "Live Events":
            continue
        to_check.append((idx, ch))

    dead_indices = set()
    
    def check_one(item):
        idx, ch = item
        alive = is_url_alive(ch['url'])
        return idx, ch, alive

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(check_one, item): item for item in to_check}
        for future in as_completed(futures):
            idx, ch, alive = future.result()
            if not alive:
                dead_indices.add(idx)
                print(f"  DEAD  → {ch['original_name']}")
            else:
                print(f"  ALIVE → {ch['original_name']}")

    print(f"\nTotal dead channels found: {len(dead_indices)}")

    # এখন মৃতগুলোর জন্য ব্যাকআপ থেকে সচল লিংক খুঁজি
    final_output = "#EXTM3U\n"
    updated_count = 0
    failed_to_update = 0

    for idx, ch in enumerate(main_channels):
        # পুরোনো Live Events রিমুভ
        if ch['group'] == "Live Events":
            continue
            
        info = ch['info']
        url = ch['url']
        
        if idx in dead_indices:
            candidates = backup_candidates.get(ch['name'], [])
            if candidates:
                new_url = find_working_url(ch['name'], candidates)
                if new_url and new_url != url:
                    url = new_url
                    print(f"Updated: {ch['original_name']}")
                    updated_count += 1
                else:
                    print(f"No working backup for: {ch['original_name']}")
                    failed_to_update += 1
            else:
                print(f"No backup found for: {ch['original_name']}")
                failed_to_update += 1
                
        final_output += f"{info}\n{url}\n"

    # ========== লাইভ স্পোর্টস যুক্ত করা (আগের মতোই) ==========
    for ch in live_channels:
        info = ch['info']
        if 'group-title=' in info:
            info = re.sub(r'group-title="[^"]*"', 'group-title="Live Events"', info)
        else:
            parts = info.rsplit(',', 1)
            if len(parts) == 2:
                info = f"{parts[0]} group-title=\"Live Events\",{parts[1]}"
            else:
                info = f"{info} group-title=\"Live Events\""
                
        final_output += f"{info}\n{ch['url']}\n"

    with open(MAIN_M3U, 'w', encoding='utf-8') as f:
        f.write(final_output)
        
    print(f"\nPlaylist updated successfully!")
    print(f"Channels updated (dead → working): {updated_count}")
    print(f"Dead channels with no working backup: {failed_to_update}")
    print(f"Live Events channels added: {len(live_channels)}")


if __name__ == "__main__":
    main()
