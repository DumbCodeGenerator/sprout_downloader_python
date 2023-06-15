import re, pickle, base64, json, sys, os, shutil, subprocess
import multiprocessing as mp

import m3u8, requests, validators
from Crypto.Cipher import AES

from colorama import init, Fore, Style
init(autoreset=True)

def stop():
    input('Stopped. Press any button to continue...')
    sys.exit()

def printError(error):
    print(Fore.RED + Style.BRIGHT + "\n" + error)
    stop()

def saveSegment(queue, currentSegm):
    args = queue.get()
    print(Fore.GREEN + Style.DIM + "\nDownloading segments: " + str(currentSegm + 1) + '/' + str(args['total']))
    with requests.get(args['url'], stream=True) as tsStream:
        with open(args['title'] + '/' + args['filename'], "wb") as f:
            shutil.copyfileobj(tsStream.raw, f)
        return f.name

if __name__ == '__main__':
    if len(sys.argv) != 2:
        videoUrl = input('Input video URL: ')
    else:
        videoUrl = sys.argv[1]

    if not validators.url(videoUrl):
        printError("Invalid URL")

    session = requests.Session()

    data = session.get(videoUrl)
    if data.status_code != 200 and re.search(r"Password Protected Video", data.text, re.I):
        password = input('Need password: ')
        token = re.search(r"name='authenticity_token' value='(.*?)'", data.text).group(1)
        data = session.post(videoUrl, data={'password':password, 'authenticity_token':token, '_method':'put'})
        if data.status_code != 200:
            printError("Wrong password")
        else:
            data = requests.get(re.search(r'<meta\s*content="(.*?)"\s*name="twitter:player"\s*\/>', data.text).group(1)).text
    elif data.status_code != 200:
        printError("Can't get the link. Status code: %s" % data.status_code)
    elif "sproutvideo.com" in videoUrl:
        data = data.text
    else:
        y_or_n = ""
        while y_or_n.lower() != "n" or y_or_n.lower() != "y":
            y_or_n = input('Probably URL is not related to sproutvideos\nStill try to work with it? y/n: ')
            y_or_n = y_or_n.strip()
            if y_or_n.lower() == "n":
                stop()
            elif y_or_n.lower() != "y":
                print(Fore.RED + Style.BRIGHT + 'Wrong answer. Please type "y" or "n"\n')

    data = re.search(r"var dat = '(.*?)'", data).group(1)
    data = base64.b64decode(data).decode('utf8')
    data = json.loads(data)

    # Remove the double quotes in the title name
    title = data.get('title').replace('"', '')

    m3u8Param = data.get('signatures').get('m')
    keyParam = data.get('signatures').get('k')
    tsParam = data.get('signatures').get('t')

    def paramToSig(param):
        return "?Policy=" + param.get('CloudFront-Policy') + "&Signature=" + param.get('CloudFront-Signature') + "&Key-Pair-Id=" + param.get('CloudFront-Key-Pair-Id') + "&sessionID=" + data.get('sessionID')

    def sign(url):
        if url.endswith('m3u8'):
            return url + paramToSig(m3u8Param)
        elif url.endswith('key'):
            return url + paramToSig(keyParam)
        else:
            return url + paramToSig(tsParam)

    baseUrl = 'https://hls2.videos.sproutvideo.com/' + data.get('s3_user_hash') + '/' + data.get('s3_video_hash') + '/video/'

    m3u8_obj = m3u8.load(sign(baseUrl + 'index.m3u8'))
    playlists_count = len(m3u8_obj.playlists)

    print()

    for i in range(playlists_count):
        print('%s. %s' % (str(i+1), m3u8_obj.playlists[i].uri.split('.')[0] + 'p'))

    playlist = 0
    while playlist < 1 or playlist > playlists_count:
        try:
            playlist = int(input('\nSelect quality: '))
            if playlist < 1 or playlist > playlists_count:
                print(Fore.YELLOW + Style.DIM + 'Wrong number')
        except ValueError:
            printError('Invalid input')

    play_link = baseUrl + m3u8_obj.playlists[playlist-1].uri

    m3u8_obj = m3u8.load(sign(play_link))

    key_obj = m3u8_obj.keys[-1]
    keyURI = baseUrl + key_obj.uri
    iv = bytes.fromhex(key_obj.iv[2:])

    keyBytes = session.get(sign(keyURI)).content

    cipher = AES.new(keyBytes, AES.MODE_CBC, iv=iv)


    m = mp.Manager()
    queue = m.Queue()

    totalSegm = len(m3u8_obj.segments)

    if not os.path.exists(title):
        os.mkdir(title)

    for segment in m3u8_obj.segments:
        queue.put({'url': sign(baseUrl + segment.uri), 'filename': segment.uri, 'title': title, 'total': totalSegm})

    with mp.Pool() as pool:
        ts_filenames = pool.starmap(saveSegment, [(queue, i) for i in range(totalSegm)])
        ts_filenames.sort()

    ts_name = title + ".ts"
    mp4_name = title + ".mp4"

    print(Fore.YELLOW + Style.DIM + "\nConcat the segments...")
    ts_filenames.sort()
    with open(ts_name, 'wb') as merged:
        for ts_file in ts_filenames:
            with open(ts_file, 'rb') as mergefile:
                merged.write(cipher.decrypt(mergefile.read()))

    shutil.rmtree(title)

    print(Fore.YELLOW + Style.DIM + "Convert to mp4...")
    p = subprocess.run(['ffmpeg', '-y', '-i', ts_name, '-map', '0', '-c', 'copy', mp4_name], capture_output=True)
    if p.returncode == 0:
        os.remove(ts_name)
    else:
        print(Fore.YELLOW + Style.DIM + "FFMpeg not found. File not converted!")

    print(Fore.GREEN + Style.DIM + '\nVideo downloaded!')
    stop()
