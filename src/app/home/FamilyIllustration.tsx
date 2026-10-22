// 디자인 레퍼런스의 정적 일러스트만 옮긴다. 데모 상태와 동작은 사용하지 않는다.
export function FamilyIllustration() {
  return (
    <div className="min-h-[210px] overflow-hidden md:min-h-[335px]">
      <svg className="h-full min-h-[210px] w-full" role="img" viewBox="0 0 450 340" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg" aria-label="서로 기대 웃는 가족의 따뜻한 일러스트">
      <defs>
      <linearGradient id="ongi-home-family-background" x1="0" y1="0" x2="1" y2="1">
      <stop stopColor="#f7e4c7"/>
      <stop offset="1" stopColor="#d3e1ce"/>
      </linearGradient>
      </defs>
      <rect width="450" height="340" fill="url(#ongi-home-family-background)"/>
      <circle cx="340" cy="65" r="112" fill="#fff4dc"/>
      <path d="M0 282Q104 224 222 267T450 254V340H0z" fill="#b0cbb1" opacity=".5"/>
      <path d="M61 340c5-117 42-162 108-161s105 45 115 161" fill="#7c9d8c"/>
      <path d="M208 340c2-120 54-166 116-161s92 59 102 161" fill="#d68d76"/>
      <path d="M126 177h57l1 37-24 22-35-24z" fill="#f3bba1"/>
      <path d="M283 178h54v34l-25 20-31-19z" fill="#eeb497"/>
      <ellipse cx="153" cy="120" rx="62" ry="75" fill="#88827a"/>
      <ellipse cx="158" cy="137" rx="51" ry="62" fill="#f4baa2"/>
      <path d="M103 125q-20-88 46-83 71-3 59 84l-15-24c-35 0-47-15-53-28-3 18-20 37-37 51" fill="#aaa49a"/>
      <path d="M128 139q8-5 17 0m30 0q8-5 17 0" stroke="#765447" strokeWidth="3" strokeLinecap="round"/>
      <path d="M142 170q16 14 30 0" stroke="#ab6b58" strokeWidth="3.3" fill="none" strokeLinecap="round"/>
      <ellipse cx="309" cy="111" rx="59" ry="80" fill="#4b3d39"/>
      <ellipse cx="312" cy="138" rx="50" ry="62" fill="#edb496"/>
      <path d="M259 130q-10-81 57-94c62-2 62 68 43 99-22-11-32-26-40-46-15 29-33 35-60 41" fill="#4b3d39"/>
      <path d="M280 141q8-5 17 0m28 0q8-5 17 0" stroke="#755047" strokeWidth="3" strokeLinecap="round"/>
      <path d="M296 172q16 15 31 0" fill="none" stroke="#a96755" strokeWidth="3.3" strokeLinecap="round"/>
      <path d="M217 275q16-43 54-49l36 14" stroke="#eeb497" strokeWidth="22" strokeLinecap="round" fill="none"/>
      <path d="M273 219q15 8 28 20" stroke="#7a9d84" strokeWidth="25" fill="none" strokeLinecap="round"/>
      <path d="M352 185q41 20 54 78" stroke="#b67861" strokeWidth="36" strokeLinecap="round" fill="none"/>
      <path d="M42 84q11-9 22 0m-7-11v22" stroke="#fff" opacity=".6" strokeWidth="3"/>
      <path d="M379 64q9-7 17 0" stroke="#fff" opacity=".9" strokeWidth="3"/>
      </svg>
      </div>
  );
}

