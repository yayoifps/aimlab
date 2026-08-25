"""キャラクター画像を index.html に埋め込むビルドスクリプト。

使い方:
    py build_sprites.py

aimlab/src/ に透過 PNG を置きます。

    01.png    ふだんの立ちポーズ（的として出現する画像）
    01_1.png  撃たれたときのポーズ（任意。無ければ立ちポーズのままフェードします）
    02.png / 02_1.png ...

    names.json  リザルト画面に出す表示名（任意）
                { "01": "izumii", "02": "kun" }

    voice/      撃破時に鳴る音声（任意）。ファイル名の先頭「-」までがキャラ番号。
                同じ番号が複数あれば、倒すたびにランダムで選ばれます。
                  voice/01-1.mp3  voice/01-2.mp3
                  voice/02-1.mp3  voice/02-2.mp3

・アルファのバウンディングボックスでトリミング
・立ちポーズの高さを MAX_H に揃え、撃たれポーズには「同じ倍率」を掛ける
  （元画像のスケールが共通なので、これで体の大きさが揃います）
・base64 data URI 化して index.html の SPRITES_BEGIN / SPRITES_END を書き換え

キャラを増やすときは 03.png / 03_1.png を足してもう一度実行するだけ。
"""
import base64
import io
import os
import re
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
HTML = os.path.join(HERE, "index.html")
MAX_H = 560           # 立ちポーズの縦解像度
ALPHA_FLOOR = 8       # これ未満のアルファは完全透明に落とす（判定のノイズ除去）


def trimmed(path):
    """透明部分を落としたRGBA画像を返す。"""
    im = Image.open(path).convert("RGBA")
    a = im.getchannel("A").point(lambda v: 0 if v < ALPHA_FLOOR else v)
    im.putalpha(a)
    box = im.getbbox()
    return im.crop(box) if box else im


def encode(im):
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    raw = buf.getvalue()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii"), len(raw)


def json_str(s):
    """JS の文字列リテラルとして安全に出力する。"""
    import json
    return json.dumps(s, ensure_ascii=False)


def scaled(im, factor):
    w = max(1, round(im.width * factor))
    h = max(1, round(im.height * factor))
    return im.resize((w, h), Image.LANCZOS)


def main():
    if not os.path.isdir(SRC):
        sys.exit("src/ が見つかりません: " + SRC)

    bases = sorted(
        f for f in os.listdir(SRC)
        if f.lower().endswith(".png")
        and not f.lower().startswith("raw")
        and "_" not in os.path.splitext(f)[0]
    )
    if not bases:
        sys.exit("src/ に立ちポーズの PNG がありません（01.png など）")

    names = {}
    names_path = os.path.join(SRC, "names.json")
    if os.path.exists(names_path):
        import json
        with open(names_path, "r", encoding="utf-8") as fh:
            names = json.load(fh)

    entries, total = [], 0
    for f in bases:
        stem = os.path.splitext(f)[0]

        base = trimmed(os.path.join(SRC, f))
        factor = MAX_H / base.height
        base_out = scaled(base, factor)
        base_uri, base_bytes = encode(base_out)
        total += base_bytes

        hit_uri, hit_scale, hit_note = "", 1.0, "—"
        hit_path = os.path.join(SRC, stem + "_1.png")
        if os.path.exists(hit_path):
            hit = trimmed(hit_path)
            # 立ちポーズと同じ倍率を掛けることで体格を揃える
            hit_out = scaled(hit, factor)
            hit_uri, hit_bytes = encode(hit_out)
            total += hit_bytes
            hit_scale = hit_out.height / MAX_H
            hit_note = "%dx%d  %.1f KB  scale %.3f" % (
                hit_out.width, hit_out.height, hit_bytes / 1024, hit_scale)

        label = names.get(stem, stem)
        entries.append((stem, label, base_out.size, base_uri, hit_uri, hit_scale))
        print("%-4s  %-10s base %dx%d  %6.1f KB   hit %s"
              % (stem, label, base_out.width, base_out.height, base_bytes / 1024, hit_note))

    body = "const CHARACTER_SPRITES = [\n"
    for stem, label, size, base_uri, hit_uri, hit_scale in entries:
        body += "  /* %s = %s  %dx%d */\n  {\n" % (stem, label, size[0], size[1])
        body += "    id: %s,\n" % json_str(stem)
        body += "    name: %s,\n" % json_str(label)
        body += "    src: '%s',\n" % base_uri
        if hit_uri:
            body += "    hit: '%s',\n" % hit_uri
            body += "    hitScale: %.4f,\n" % hit_scale
        body += "  },\n"
    body += "];\n"

    with open(HTML, "r", encoding="utf-8") as fh:
        html = fh.read()

    new, n = re.subn(
        r"(/\* SPRITES_BEGIN \*/\n).*?(/\* SPRITES_END \*/)",
        lambda m: m.group(1) + body + m.group(2),
        html,
        flags=re.S,
    )
    if n != 1:
        sys.exit("index.html に SPRITES_BEGIN / SPRITES_END マーカーが見つかりません")

    # 撃破ボイス。ファイル名の先頭「-」までをキャラ番号として束ねる。
    voice_dir = os.path.join(SRC, "voice")
    voices, vbytes = {}, 0
    if os.path.isdir(voice_dir):
        for f in sorted(os.listdir(voice_dir)):
            if not f.lower().endswith((".mp3", ".ogg", ".wav", ".m4a")):
                continue
            key = os.path.splitext(f)[0].split("-")[0]
            with open(os.path.join(voice_dir, f), "rb") as fh:
                raw = fh.read()
            voices.setdefault(key, []).append(base64.b64encode(raw).decode("ascii"))
            vbytes += len(raw)
            print("voice %-12s -> %-4s %6.1f KB" % (f, key, len(raw) / 1024))

    vbody = "const CHARACTER_VOICES = {\n"
    for key in sorted(voices):
        vbody += "  %s: [\n" % json_str(key)
        for b in voices[key]:
            vbody += "    '%s',\n" % b
        vbody += "  ],\n"
    vbody += "};\n"

    new, nv = re.subn(
        r"(/\* VOICES_BEGIN \*/\n).*?(/\* VOICES_END \*/)",
        lambda m: m.group(1) + vbody + m.group(2),
        new,
        flags=re.S,
    )
    if nv != 1:
        sys.exit("index.html に VOICES_BEGIN / VOICES_END マーカーが見つかりません")
    if voices:
        print("-> 撃破ボイス %d 種 / %d 本（%.1f KB）"
              % (len(voices), sum(len(v) for v in voices.values()), vbytes / 1024))

    # ビルド識別子（画面に出るので、キャッシュで古い版を見ていないか確認できる）
    import datetime
    stamp = datetime.datetime.now().strftime("%m%d-%H%M")
    new, nb = re.subn(
        r"(/\* BUILD_BEGIN \*/\n).*?(/\* BUILD_END \*/)",
        lambda m: m.group(1) + "const BUILD = '%s';\n" % stamp + m.group(2),
        new,
        flags=re.S,
    )
    if nb == 1:
        print("build: " + stamp)

    with open(HTML, "w", encoding="utf-8") as fh:
        fh.write(new)

    print("-> index.html に %d 体を埋め込みました（画像 合計 %.1f KB）"
          % (len(entries), total / 1024))


if __name__ == "__main__":
    main()
