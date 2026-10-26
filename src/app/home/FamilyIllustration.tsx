import Image from "next/image";

/** 로그인, 홈, 개발 프리뷰에서 함께 사용하는 가족 캐릭터 일러스트. */
export function FamilyIllustration() {
  return (
    <div className="relative aspect-[4/3] min-h-[210px] overflow-hidden bg-[#f6eddb] md:aspect-auto md:min-h-[335px]">
      <Image
        src="/images/family-together.webp"
        alt="소파에 모여 미소 짓는 아버지, 어머니, 아들, 딸의 따뜻한 색연필 캐릭터 일러스트"
        fill
        priority
        sizes="(min-width: 1280px) 510px, (min-width: 768px) 45vw, 100vw"
        className="object-contain object-center"
      />
    </div>
  );
}
