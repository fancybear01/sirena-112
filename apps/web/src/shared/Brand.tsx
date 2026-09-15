import { Box, Text } from '@mantine/core';
import { IconPhoneCalling } from '@tabler/icons-react';

export function Brand({ inverse = false }: { inverse?: boolean }) {
  return (
    <div className={`brand ${inverse ? 'brand--inverse' : ''}`}>
      <Box className="brand__mark" aria-hidden="true">
        <IconPhoneCalling size={22} stroke={2.1} />
      </Box>
      <div>
        <Text className="brand__name">Сирена<span>112</span></Text>
        <Text className="brand__caption">Учебная платформа</Text>
      </div>
    </div>
  );
}
