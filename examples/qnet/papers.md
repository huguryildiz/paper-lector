# Quantum network example: papers

Question:

> Çok kullanıcılı bir kuantum ağında entanglement dağıtımını zamanlamak için hangi yöntemler (optimizasyon, heuristik, RL) kullanılmış ve hangi metriklerle karşılaştırılmış?

A real run from search to ranking. An OpenAlex keyword search found 47 works (`runs/search_v2.jsonl`). Reading the abstracts, 12 were off topic and dropped, leaving 35 (`runs/search_v2_filtered.jsonl`). `fetch_pdf.py` got 18 open-access PDFs, most of them arXiv preprints; the rest sit behind publisher sites (`MANUAL` lines in `literature/pdfs/fetch_log.jsonl`). The PDFs are not in the repository.

`rank.py --abstracts runs/search_v2_filtered.jsonl` ranked the 18 PDFs on full text (`fused_rank`, with starting pages in the CSV) and all 33 distinct papers on their abstracts alone (`abs_fused_rank`). The two orders are separate: abstract-only scores run lower than full-text ones. Queries are in `literature/queries.json` (fused: main, subject, approach, outcome); the run record is `runs/qnet_abs_2026-10-17_run.json`.

Two `MANUAL` lines in the fetch log are not missing papers: W3021951002 is the Lee et al. PDF, fetched earlier by its arXiv id, and 2105.00418 (QuNet) is withdrawn.

| abstract rank | full-text rank | PDF | first author | year | title | id | note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | - | no | Xinrui Liu | 2025 | Quantum Network Routing Design with Dynamic Requests Scheduling in Multi-User Environments | [10.1109/iwcmc65282.2025.11059451](https://doi.org/10.1109/iwcmc65282.2025.11059451) |  |
| 2 | 2 | yes | Quang-Phong Tran | 2026 | Dynamic Entanglement Packet Scheduling for Quantum Networks | [10.1109/infocom59046.2026.11571755](https://doi.org/10.1109/infocom59046.2026.11571755) |  |
| 3 | 1 | yes | Changhao Li | 2021 | Effective routing design for remote entanglement generation on quantum networks | [10.1038/s41534-020-00344-4](https://doi.org/10.1038/s41534-020-00344-4) |  |
| 4 | - | no | Ziyue Jia | 2024 | On Fidelity-Oriented Entanglement Distribution for Quantum Switches | [10.1109/jetcas.2024.3425712](https://doi.org/10.1109/jetcas.2024.3425712) |  |
| 5 | - | no | Bing Yang | 2025 | SwappingBoost: Optimizing Entanglement Routing by Mitigating Bottlenecks in Quantum Networks | [10.1109/iwcmc65282.2025.11059641](https://doi.org/10.1109/iwcmc65282.2025.11059641) |  |
| 6 | - | no | Xiaoyu Wang | 2026 | Deep Reinforcement Learning-Based Deferred Entanglement Path Selection in Quantum Networks | [10.1109/ton.2026.3683478](https://doi.org/10.1109/ton.2026.3683478) |  |
| 7 | 4 | yes | Jian Li | 2022 | Fidelity-Guaranteed Entanglement Routing in Quantum Networks | [10.1109/tcomm.2022.3200115](https://doi.org/10.1109/tcomm.2022.3200115) |  |
| 8 | - | no | Hudson Leone | 2021 | QuNet: Cost vector analysis & multi-path entanglement routing in quantum networks | W3157943800 | withdrawn on arXiv by its author |
| 9 | - | no | Matthew Skrzypczyk | 2020 | Dynamic Time-Division Multiple Access in Noisy Intermediate-Scale Quantum Networks | W3172189854 |  |
| 10 | - | no | Wei-Hsun Huang | 2023 | A Heuristic for Entanglement Routing in Quantum Networks | [10.1109/icasi57738.2023.10179513](https://doi.org/10.1109/icasi57738.2023.10179513) |  |
| 11 | 7 | yes | Xiaojie Fan | 2025 | Near-Optimal Techniques for Distributed Entanglement Generation and Purification | [10.21203/rs.3.rs-7357320/v1](https://doi.org/10.21203/rs.3.rs-7357320/v1) |  |
| 12 | 9 | yes | Kaushik Chakraborty | 2019 | Distributed Routing in a Quantum Internet | [10.48550/arxiv.1907.11630](https://doi.org/10.48550/arxiv.1907.11630) |  |
| 13 | - | no | Lutong Chen | 2023 | Q-DDCA: Decentralized Dynamic Congestion Avoid Routing in Large-Scale Quantum Networks | [10.1109/tnet.2023.3285093](https://doi.org/10.1109/tnet.2023.3285093) |  |
| 14 | - | no | Yiming Zeng | 2024 | Multi-User Entanglement Routing Design over Quantum Internets | [10.1109/icdcs60910.2024.00033](https://doi.org/10.1109/icdcs60910.2024.00033) |  |
| 15 | 5 | yes | Evan Sutcliffe | 2023 | Multiuser Entanglement Distribution in Quantum Networks Using Multipath Routing | [10.1109/tqe.2023.3329714](https://doi.org/10.1109/tqe.2023.3329714) |  |
| 16 | 6 | yes | Zheng Zhang | 2026 | Optimized Source Placement for Multipartite State Distribution in Quantum Networks | W7211979920 |  |
| 17 | 12 | yes | Yuan Lee | 2020 | A Quantum Router Architecture for High-Fidelity Entanglement Flows in Multi-User Quantum Networks | W3021951002 |  |
| 18 | - | no | Yukun Yang | 2026 | Online Scheduling and Distribution of Quantum Circuits Over Quantum Networks | [10.1109/qcnc69040.2026.00045](https://doi.org/10.1109/qcnc69040.2026.00045) |  |
| 19 | 8 | yes | Nicolò Lo Piparo | 2025 | Quality of service in aggregated quantum networks | [10.1103/ph6d-qqwk](https://doi.org/10.1103/ph6d-qqwk) |  |
| 20 | 11 | yes | Muhammad Daud | 2024 | Scaling network topologies for multi-user entanglement distribution | [10.1007/s11128-024-04423-9](https://doi.org/10.1007/s11128-024-04423-9) |  |
| 21 | - | no | Yangming Zhao | 2021 | Redundant Entanglement Provisioning and Selection for Throughput Maximization in Quantum Networks | [10.1109/infocom42981.2021.9488850](https://doi.org/10.1109/infocom42981.2021.9488850) |  |
| 22 | 3 | yes | Zirui Xiao | 2024 | Purification scheduling control for throughput maximization in quantum networks | [10.1038/s42005-024-01796-2](https://doi.org/10.1038/s42005-024-01796-2) |  |
| 23 | - | no | Shu-Ming Hu | 2026 | Resource-Effcient Quantum Beneš Networks | [10.1088/1674-1056/aeab5d](https://doi.org/10.1088/1674-1056/aeab5d) |  |
| 24 | 14 | yes | Jazz E Z Ooi | 2026 | Impact of topology on multipartite entanglement distribution protocols in quantum networks | [10.1364/jocn.600057](https://doi.org/10.1364/jocn.600057) |  |
| 25 | 18 | yes | Vaisakh Mannalath | 2023 | Multiparty entanglement routing in quantum networks | [10.1103/physreva.108.062614](https://doi.org/10.1103/physreva.108.062614) |  |
| 26 | - | no | Wan-Ting Ho | 2024 | Online Transit Entanglement Routing in Quantum Networks: Architecture Design and Optimization | [10.1109/globecom52923.2024.10901422](https://doi.org/10.1109/globecom52923.2024.10901422) |  |
| 27 | 15 | yes | Rui Wang | 2026 | Dynamic Entanglement Distribution for Multi-User and Multi-Protocol Quantum Networking | [10.48550/arxiv.2607.15262](https://doi.org/10.48550/arxiv.2607.15262) |  |
| 28 | 10 | yes | Jake Smith | 2026 | Tools for Reducing Service Time in Near-Term Quantum Networks | [10.48550/arxiv.2608.20954](https://doi.org/10.48550/arxiv.2608.20954) |  |
| 29 | 13 | yes | Si‐Yi Chen | 2026 | Quantum Routing Beyond Pathfinding: Multipartite Entanglement Complementation | [10.48550/arxiv.2604.13834](https://doi.org/10.48550/arxiv.2604.13834) |  |
| 30 | 16 | yes | Zhaohui Yang | 2023 | Reconfigurable Quantum Internet Service Provider | [10.1109/icc45041.2023.10279003](https://doi.org/10.1109/icc45041.2023.10279003) |  |
| 31 | 17 | yes | Yaliang Shi | 2026 | QUASAR: Quantum Satellite Architecture and Routing Simulator | [10.48550/arxiv.2609.04920](https://doi.org/10.48550/arxiv.2609.04920) |  |
| 32 | - | no | Shao-Min Huang | 2024 | Authorizable Tripartite Entanglement Routing via 3-GHZ State in Quantum Networks | [10.1109/globecom52923.2024.10901779](https://doi.org/10.1109/globecom52923.2024.10901779) |  |
| - | - | no | Chenliang Tian | 2026 | RADAR-Q: Resource-Aware Distributed Asynchronous Routing for Entanglement Distribution in Multi-tenant Quantum Networks | [10.1007/978-3-032-32636-2_41](https://doi.org/10.1007/978-3-032-32636-2_41) | no abstract in OpenAlex, unranked |
