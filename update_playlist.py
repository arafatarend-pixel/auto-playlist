import requests
import re
import os

MAIN_M3U = 'Playlist.m3u'
URLS_FILE = 'urls.txt'

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
            name = normalize_name(original_name)   # ← এখানে নরমালাইজ করা হচ্ছে
            
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

def main():
    if not os.path.exists(URLS_FILE) or not os.path.exists(MAIN_M3U):
        print("Required files not found!")
        return
        
    with open(URLS_FILE, 'r', encoding='utf-8') as f:
        urls = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
    
    if len(urls) < 2:
        print("Not enough URLs in urls.txt")
        return

    # শেষের অংশকে স্পোর্টস ধরা হচ্ছে (এখন আরো ফ্লেক্সিবল)
    # তুমি urls.txt তে স্পোর্টস লিংকগুলো একদম নিচে রাখবে
    sports_count = 2   # ← এখানে কতগুলো স্পোর্টস সোর্স আছে সেটা লিখো
    backup_urls = urls[:-sports_count] if len(urls) > sports_count else []
    sports_urls = urls[-sports_count:] if len(urls) >= sports_count else urls

    with open(MAIN_M3U, 'r', encoding='utf-8') as f:
        main_text = f.read()
    
    main_channels = parse_m3u(main_text)

    # ব্যাকআপ ডিকশনারি তৈরি
    backup_dict = {}
    for b_url in backup_urls:
        print(f"Fetching backup: {b_url}")
        b_text = fetch_m3u(b_url)
        if b_text:
            b_channels = parse_m3u(b_text)
            for ch in b_channels:
                # আগে থেকে না থাকলেই রাখবে (আগের সোর্স প্রায়োরিটি পাবে)
                if ch['name'] not in backup_dict:
                    backup_dict[ch['name']] = ch['url']

    # লাইভ স্পোর্টস ফেচ করা
    live_channels = []
    for s_url in sports_urls:
        print(f"Fetching sports: {s_url}")
        s_text = fetch_m3u(s_url)
        if s_text:
            s_channels = parse_m3u(s_text)
            live_channels.extend(s_channels)

    # ফাইনাল প্লেলিস্ট তৈরি
    final_output = "#EXTM3U\n"
    updated_count = 0
    
    for ch in main_channels:
        # পুরোনো Live Events রিমুভ করে নতুন করে যুক্ত করবো
        if ch['group'] == "Live Events":
            continue
            
        info = ch['info']
        url = ch['url']
        
        if ch['name'] in backup_dict:
            url = backup_dict[ch['name']]
            print(f"Updated: {ch['original_name']}")
            updated_count += 1
            
        final_output += f"{info}\n{url}\n"

    # লাইভ স্পোর্টস যুক্ত করা
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
    print(f"Total channels updated: {updated_count}")

if __name__ == "__main__":
    main()
