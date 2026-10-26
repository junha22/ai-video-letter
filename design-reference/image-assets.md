# 캐릭터 이미지 에셋

현재 화면은 색연필과 과슈 손그림 느낌의 2D 가족 캐릭터를 사용합니다. 따뜻한 크림·세이지 색감, 둥근 얼굴, 작은 미소, 은은한 종이 질감으로 귀엽고 편안한 인상을 줍니다.

- 생성 방식: 내장 `image_gen` 도구 (`illustration-story`)
- 가족 일러스트: `public/images/family-together.webp` — 로그인, 홈, 개발 프리뷰 메인·대시보드. 아버지·어머니·아들·딸로 남성 2명, 여성 2명.
- 딸 캐릭터: `public/images/daughter-character.webp`
- 아들 캐릭터: `public/images/son-character.webp`
- 개발 프리뷰 상단에서 아들·딸 예시를 선택하면 등록 완료·영상 확인·부모님 시청 예시가 동일 인물로 함께 바뀝니다. 기본 예시는 아들입니다.
- 사진 등록 안내에는 선택한 예시와 다른 캐릭터를 함께 보여줍니다. 실제 사진 등록 안내의 기본 예시는 딸입니다.
- 캐릭터 생성에는 가족 일러스트를 인물·화풍 참고 이미지로 사용했습니다.
- 원본의 구도와 색을 유지하며 WebP로 인코딩했습니다. 추가 패키지나 외부 이미지 호스팅은 필요하지 않습니다.
- 실제 업로드 사진과 실제 생성 영상은 기존 데이터를 사용합니다.

## 가족 캐릭터 최종 프롬프트

```text
Use case: illustration-story. Asset type: single landscape 4:3 family hero illustration for a Korean family video-letter web app. Input image 1 is a STYLE AND EXISTING CHARACTER REFERENCE only. Generate a NEW family scene in precisely the same warm colored-pencil and matte gouache picture-book style, cream paper texture, small dot eyes, subtle blush cheeks, tiny pencil noses and gentle curved smiles. Show FOUR Korean family members, exactly TWO MEN and TWO WOMEN, enjoying a quiet moment together around the ivory sofa. Keep the existing mother with gray-brown short wavy hair and oatmeal cardigan, and existing adult daughter with shoulder-length chestnut hair and sage green top. ADD a father around 60 with short softly graying hair, small round glasses and muted blue-gray knit sweater, and an adult son around 30 with short tousled dark brown hair and a muted warm terracotta casual shirt. Both adult children clearly grown up, same visual importance and face size as parents, everyone cute yet dignified. Compose a compact group in two softly staggered rows: parents seated at front, grown children leaning comfortably from behind the sofa, daughter near father and son near mother, all four faces clearly visible and close to center with no overlapping heads. Not a stiff portrait; quiet affectionate relaxed postures with small smiles and heads gently inclined. Keep all four complete heads and shoulders inside the middle 75% of canvas with wide cream margins at sides and generous space at top; no character near image edges. A tiny soft plant at far left and a low table edge at bottom, minimal setting. Flat hand-drawn human characters, softly rounded adult proportions, slightly wobbly warm brown pencil contours, muted sage/cream/terracotta/slate blue, delicate visible pencil grain, very restrained shading. Cozy, comforting and cheerful, equal visual prominence to men and women. Avoid photorealism, 3D, clay, plastic, glossy rendering, sculpted faces, anime, exaggerated baby heads, excessive scenery, floating hearts, text, logos, UI or watermark. One finished illustration, no collage.
```

## 딸 캐릭터 최종 프롬프트

```text
Use case: illustration-story. Asset type: one square character portrait for photo-registration guide and static video-letter preview in a Korean family web app. Input image 1 is a CHARACTER AND DRAWING STYLE REFERENCE only, not the edit target. Make a NEW illustration depicting ONLY the adult daughter from the RIGHT side of the reference, now facing straight toward the viewer with head upright. Keep her identifiable shoulder-length chestnut-brown hair with side part, sage green top, rounded softly drawn face, two small dark dot eyes, tiny pencil nose, tiny relaxed curved smile, rosy cheeks. A cute and comforting grown-up character, not a baby. Portrait from the upper chest up, entire head visible, centered, generous clean margin around the head, crown about 18% from top and chin about 68%, shoulders cropped at bottom. Same charming quiet 2D colored-pencil-and-gouache picture-book illustration as reference: slightly wobbly warm brown pencil outlines, matte flat color fills with delicate grain and paper texture, simple human features and restrained shading. Background only warm unpainted cream paper; no scene, no objects, no other character, no hands. Avoid realism, photographs, realistic skin, 3D, clay, plastic, sculpted faces, shiny eyes, anime, gradients, heavy shading, excessive texture, childlike infant proportions, UI, text, frame or watermark. Output one finished square portrait illustration with soft warm cream background.
```

## 아들 캐릭터 최종 프롬프트

```text
Use case: illustration-story. Asset type: one square male character portrait for Korean family video-letter photo registration and video previews. Input image 1 is a drawing style and character reference only, not an edit target. Generate a NEW illustration of ONLY the grown-up SON with terracotta shirt from upper left of the reference, now facing directly toward the viewer with his head upright. Keep his short dark brown gently tousled side-parted hair and warm terracotta loose shirt over an ivory undershirt, round softly drawn adult face, two tiny dark dot eyes, tiny pencil nose, subtle blush cheeks, a small gentle curved closed-mouth smile. Same approachable, cute and reassuring adult proportions as reference, adult about 30, no childlike baby head. Upper-chest portrait centered in a square, entire head visible, crown around 15% from top, chin around 65%, shoulders cropped at bottom. Match the existing daughter portrait style: fine gently irregular warm brown colored-pencil contours, matte gouache color fields, delicate pencil grain and cream paper texture, flat 2D with very little shading. Background only pale warm cream paper, no scenery or objects, no hands, no other people. Avoid photographs, realistic skin, 3D, clay, plastic, glossy materials, anime eyes, gradients, dramatic shadows, text, watermark, frame or UI. One finished square illustration.
```

