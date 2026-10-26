import Image from "next/image";

const PORTRAITS = {
  daughter: { src: "/images/daughter-character.webp", alt: "초록색 옷을 입고 정면을 보며 부드럽게 미소 짓는 딸 캐릭터 일러스트" },
  son: { src: "/images/son-character.webp", alt: "따뜻한 주황색 셔츠를 입고 정면을 보며 부드럽게 미소 짓는 아들 캐릭터 일러스트" },
};

/** 사진 가이드와 프리뷰에서 사용하는 정적 캐릭터 예시. */
export function SamplePortrait({ variant = "daughter", sizes = "(min-width: 768px) 440px, 90vw" }: { variant?: keyof typeof PORTRAITS; sizes?: string }) {
  const portrait = PORTRAITS[variant];
  return (
    <span className="relative block h-full w-full">
      <Image
        src={portrait.src}
        alt={portrait.alt}
        fill
        sizes={sizes}
        className="object-cover object-center"
      />
    </span>
  );
}
