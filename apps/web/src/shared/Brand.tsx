import { IconPhoneCalling } from '@tabler/icons-react';

export function Brand() {
  return (
    <div className="brand">
      <span className="brand__mark" aria-hidden="true">
        <IconPhoneCalling size={21} stroke={2} />
      </span>
      <span className="brand__name">Сирена<span>112</span></span>
    </div>
  );
}
