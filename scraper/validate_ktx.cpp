// SPDX-FileCopyrightText: 2026 ARMSX2 Dev Team
// SPDX-License-Identifier: GPL-3.0+
//
// Parse KTX1 files with the ARMSX2 app's own parser (GSTextureKTX.h) and exit 0 only if every
// one loads. Usage: validate_ktx <max-texture-size> <file>...
// The Dockerfile builds it against a pinned ARMSX2 checkout; GPL like the header it includes.

#include "GS/Renderers/Common/GSTexture.h"
#include "GS/Renderers/HW/GSTextureKTX.h"

#include <cstdio>
#include <fstream>
#include <iostream>
#include <iterator>
#include <vector>

GSTexture::BlockInfo GSTexture::GetBlockInfo(Format format)
{
	switch (format)
	{
		case Format::ASTC4x4: return {4, 4, 16};
		case Format::ASTC5x4: return {5, 4, 16};
		case Format::ASTC5x5: return {5, 5, 16};
		case Format::ASTC6x5: return {6, 5, 16};
		case Format::ASTC6x6: return {6, 6, 16};
		case Format::ASTC8x5: return {8, 5, 16};
		case Format::ASTC8x6: return {8, 6, 16};
		case Format::ASTC8x8: return {8, 8, 16};
		case Format::ASTC10x5: return {10, 5, 16};
		case Format::ASTC10x6: return {10, 6, 16};
		case Format::ASTC10x8: return {10, 8, 16};
		case Format::ASTC10x10: return {10, 10, 16};
		case Format::ASTC12x10: return {12, 10, 16};
		case Format::ASTC12x12: return {12, 12, 16};
		default: return {};
	}
}

int main(int argc, char** argv)
{
	if (argc < 3)
		return 2;

	const u32 max_texture_size = static_cast<u32>(std::atoi(argv[1]));
	for (int i = 2; i < argc; i++)
	{
		std::ifstream input(argv[i], std::ios::binary);
		const std::vector<u8> data(std::istreambuf_iterator<char>(input), {});
		if (data.size() < KTX::HEADER_SIZE)
		{
			std::cerr << "INVALID " << argv[i] << " short read\n";
			return 1;
		}

		KTX::ContainerInfo info{};
		KTX::ParseResult result = KTX::ParseHeader(data.data(), data.size(), &info, max_texture_size);
		if (result == KTX::ParseResult::Ok)
			result = KTX::ValidateKeyValueData(data.data() + KTX::HEADER_SIZE, info.key_value_bytes);

		std::array<KTX::LevelInfo, KTX::MAX_MIP_LEVELS> levels{};
		if (result == KTX::ParseResult::Ok)
			result = KTX::BuildLevelLayout(info, static_cast<s64>(data.size()), &levels);

		for (u32 level = 0; result == KTX::ParseResult::Ok && level < info.mip_count; level++)
		{
			result = KTX::ValidateLevelSize(
				data.data() + levels[level].data_offset - sizeof(u32), sizeof(u32), levels[level]);
		}

		if (result != KTX::ParseResult::Ok)
		{
			std::cerr << "INVALID " << argv[i] << " result " << static_cast<unsigned>(result) << '\n';
			return 1;
		}
	}

	return 0;
}
