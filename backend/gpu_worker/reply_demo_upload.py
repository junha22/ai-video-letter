"""시험용: 녹음 파일들을 시니어 음성 답장처럼 대화방에 차례로 보낸다 (docs/REPLY_ANALYSIS.md 7절, 끝까지 확인).

시니어 화면은 마이크로만 녹음하므로, 미리 녹음한 WAV를 공유 링크로 직접 올릴 때 쓴다.
같은 분의 답장을 순서대로 보내면 워커가 하나씩 분석해서 4번째부터 평소 목소리와 비교된다.
먼저 자녀 화면에서 그 대화방의 '답장 살펴보기'를 켜 둔다. 시니어 안내 확인(voice-notice)은 이 스크립트가 한다.

주의: 답장 분석은 받아쓴 글을 CLOVA Studio(외부 서비스)로 보낸다. AI Hub 음성(reply-demo10)은 외부 서비스로 보내면 안 되는
조건이 있으니, CLOVA로 분석하는 시연에는 직접 녹음한 음성을 쓴다. 폴더에 wav만 두면 파일 이름 순서로 보낸다.

  python gpu_worker/reply_demo_upload.py --token <공유 링크 토큰> --folder <직접 녹음한 wav 폴더>
  (--base 기본 http://127.0.0.1:8000 = API. 웹 주소 http://localhost:3000 도 된다)
실제 사용자 데이터가 있는 서버에는 쓰지 않는다. 시험용 계정·대화방에만 보낸다.
"""

import argparse
import csv
import sys
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True, help="공유 링크 /w/<토큰>의 토큰")
    parser.add_argument("--folder", type=Path, required=True, help="demo_list.csv와 wavs 폴더가 있는 곳 (또는 wav 폴더)")
    parser.add_argument("--parent", help="demo_list.csv의 parent_id (비우면 첫 번째 부모님)")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--yes", action="store_true", help="CLOVA로 보낸다는 경고를 확인한 것으로 하고 묻지 않는다")
    args = parser.parse_args()

    print("주의: 답장 분석은 받아쓴 글을 네이버 클로바(CLOVA Studio, 외부 서비스)로 보내요.\n"
          "      AI Hub 음성(reply-demo10)은 외부 서비스로 보내면 안 되는 조건이 있으니, CLOVA로 분석하는 시연에는 직접 녹음한 음성을 쓰세요.")
    if not args.yes and input("직접 녹음한 음성이 맞으면 y를 누르세요: ").strip().lower() != "y":
        sys.exit("보내지 않았어요.")

    listing = args.folder / "demo_list.csv"
    wavs = args.folder / "wavs" if (args.folder / "wavs").is_dir() else args.folder
    if listing.exists():
        rows = list(csv.DictReader(open(listing, encoding="utf-8-sig")))
        parent = args.parent or rows[0]["parent_id"]
        files = [wavs / r["file"] for r in sorted((r for r in rows if r["parent_id"] == parent), key=lambda r: int(r["order"]))]
    else:
        files = sorted(wavs.glob("*.wav"))
    files = files[: args.limit]
    if not files:
        sys.exit("보낼 음성이 없어요")

    with httpx.Client(base_url=args.base.rstrip("/"), timeout=120) as c:
        room = c.get(f"/api/watch/{args.token}/conversation")
        room.raise_for_status()
        voice = room.json().get("voice_reply")
        if not voice or not voice["available"]:
            sys.exit("이 대화방은 음성 답장을 받지 않아요. REPLY_ANALYSIS_ENABLED=true와 자녀 화면의 '답장 살펴보기 켜기'를 확인하세요.")
        c.post(f"/api/watch/{args.token}/voice-notice").raise_for_status()
        for n, path in enumerate(files, 1):
            with open(path, "rb") as f:
                r = c.post(f"/api/watch/{args.token}/voice-replies", data={"client_id": f"demo-{path.stem}"[:80]},
                           files={"file": (path.name, f, "audio/wav")})
            if r.status_code != 200:
                sys.exit(f"{n}번째({path.name}) 보내기 실패: {r.status_code} {r.text[:200]}")
            print(f"{n}/{len(files)} 보냄: {path.name} → 답장 #{r.json()['id']} ({r.json().get('audio_seconds')}초)")
    print("워커가 하나씩 분석해요. 자녀 화면의 대화방에서 결과를 확인하세요.")


if __name__ == "__main__":
    main()
