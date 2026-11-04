# 开源宠物营养 / 配方计算工具参考（GitHub）

联网完善时发现的可复用开源项目（检索日 2026-10-21，来源 GitHub）。用于配方计算、营养数据库、能量/阶段换算的二次开发起点。使用前请核对许可证与数据时效性。

| 项目 | 语言/栈 | 功能 | 许可证 | 活跃度 | 备注 |
| --- | --- | --- | --- | --- | --- |
| [WorldOfRations](https://github.com/developersworkspace/WorldOfRations) | PHP/MySQL | 真·最低成本线性规划配方的多物种（含犬猫）配方系统，内置 NRC/ARC/AAFCO 营养数据库 | MIT | 2017 后停更 | 含可修改的养分/原料数据库，适合做本地营养 DB 起点 |
| [tailmate](https://github.com/wolfdenpublishing/tailmate) | 纯 HTML/JS | 家用犬粮计算器：RER + 生命周期系数（含妊娠/泌乳），100+ 原料含安全注与烹饪损失比 | MIT | 2026 活跃 | 含 AAFCO 营养指引，配合 BalanceIT 补剂计算 |
| [PetFoodCalculator](https://github.com/jasmine-glancy/PetFoodCalculator) | Flask(Python) | RER/DER 计算（犬猫），按 BCS/妊娠/哺乳给喂食建议，链接 AAHA/AAFCO/WSAVA | Apache-2.0 | 2024 | 教学/原型参考 |
| [OpenAnimalNutrition](https://github.com/baraline/OpenAnimalNutrition) | Python | 动物（猫犬）膳食规划与食品质量评分，含健康状态调整 | GPL-3.0 | 2022 | 4★，含 input_data JSON 养分数据，可借鉴数据结构 |
| [jonniesweb/dogfood](https://github.com/jonniesweb/dogfood) | React/Vite | 犬每日喂食量计算（生食/干粮/混喂），按体重/年龄分阶 | 未声明 | 2025 | 仅喂食量，不含营养浓度核算 |
| [MyreLab/petfood_calculator](https://github.com/MyreLab/petfood_calculator) | Python | 按宠物体重算每日营养需要，输出湿粮+干粮组合比例（基于标签数据，可自传） | GPL-3.0 | 2024 | 用线性回归动态计算猫需要，适合做定制脚本起点 |
| [je-von/canine-calc](https://github.com/je-von/canine-calc) | Swift | WWDC23 获奖 App，犬每日能量/克数、理想体重、BCS 教学 | 未声明 | 2023 | 教学/科普参考，含 Purina BCS 图 |

## 使用建议

- **营养数据库底座**：优先参考 WorldOfRations（内置 NRC/AAFCO 库）与 OpenAnimalNutrition 的 JSON 结构。
- **能量/RER 计算**：tailmate、PetFoodCalculator 的 RER + 生命周期系数实现可直接对照本 skill 的 `scripts/nutrient_calc.py` 验证。
- **合规边界**：开源工具多依 AAFCO；销欧须以 FEDIAF 2024 为准（见 `nutrition_needs.md` §3.5/§9/§10.2）。
- **免责**：本表仅作技术资源索引，不替代兽医营养处方；自制粮必须配合兽医配方补剂方才营养完整。
