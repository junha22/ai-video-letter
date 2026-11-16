import Image from "next/image";

type FamilyPortraitProps = {
  relation: string;
  name?: string;
  className?: string;
};

/** Reuse the parents in the album cover so every family portrait has the same artwork. */
export function FamilyPortrait({ relation, name = "", className = "" }: FamilyPortraitProps) {
  const identity = `${relation} ${name}`;
  const kind = /어머니|엄마|할머니|외할머니/.test(identity)
    ? "mother"
    : /아버지|아빠|할아버지|외할아버지/.test(identity)
      ? "father"
      : "family";

  return (
    <span className={`family-portrait family-portrait--${kind} ${className}`} aria-hidden="true">
      <Image
        src="/images/family-together.webp"
        alt=""
        width={1448}
        height={1086}
        sizes="280px"
      />
    </span>
  );
}
