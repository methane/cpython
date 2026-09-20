# M22b method JIT単独: pyperformance開発screen

GILあり、PGOなし、LTOなし。mainのtracing JITとmethod JIT単独の固定buildを比較した。
C `_decimal`を両側で使用。CPU 2固定、hash seed 0、順序を逆にした2block、
各2worker・5warmup・5value・min-time 0.1秒。全workerを残した。
networkxのworker上限15秒、他60秒、仕様上限300秒。

97仕様のうち、89仕様・115結果で4runの比較が完了。
8仕様に実行失敗がある。成功結果の時間比の幾何平均は **0.9850**。
時間比はmethod/mainで、小さいほど速い。10%条件は各項目で1.10以下を要求する。
**10%条件は未達。** このscreenだけで最終性能を保証しない。

95%区間はblock内のworker単位bootstrap 4,000回。ビルド一組での推定であり、
OSのゆらぎやrebuildによる変動すべてを含む区間ではない。境界付近と超過項目は追加比較する。
このブランチには既存のC実装の変更もあり、差をfrontend単独の寄与とはみなさない。

## 10%を超えた項目

| Benchmark | method/main | 95% CI |
|---|---:|---:|
| richards_super | 1.3603 | 1.3558–1.3649 |
| richards | 1.2519 | 1.2414–1.2625 |
| scimark_lu | 1.2477 | 1.2417–1.2538 |
| logging_format | 1.1265 | 1.1227–1.1302 |
| nqueens | 1.1067 | 1.1043–1.1092 |
| shortest_path | 1.1010 | 1.0301–1.1680 |

## 全成功結果

| Benchmark | 仕様 | method/main | 95% CI | block A / B |
|---|---|---:|---:|---:|
| 2to3 | 2to3 | 0.9827 | 0.9815–0.9840 | 0.9838 / 0.9816 |
| ascii85_large | base64 | 0.9034 | 0.9030–0.9037 | 0.9035 / 0.9032 |
| ascii85_small | base64 | 1.0065 | 1.0048–1.0082 | 1.0071 / 1.0059 |
| async_generators | async_generators | 0.9664 | 0.9625–0.9703 | 0.9692 / 0.9635 |
| async_tree_cpu_io_mixed | async_tree_cpu_io_mixed | 0.9466 | 0.9387–0.9547 | 0.9409 / 0.9524 |
| async_tree_cpu_io_mixed_tg | async_tree_cpu_io_mixed_tg | 0.9553 | 0.9530–0.9577 | 0.9562 / 0.9544 |
| async_tree_eager | async_tree_eager | 0.9678 | 0.9544–0.9817 | 0.9615 / 0.9741 |
| async_tree_eager_cpu_io_mixed | async_tree_eager_cpu_io_mixed | 0.9365 | 0.9315–0.9415 | 0.9384 / 0.9345 |
| async_tree_eager_cpu_io_mixed_tg | async_tree_eager_cpu_io_mixed_tg | 0.9464 | 0.9424–0.9505 | 0.9468 / 0.9461 |
| async_tree_eager_io | async_tree_eager_io | 1.0008 | 0.9996–1.0020 | 0.9994 / 1.0022 |
| async_tree_eager_io_tg | async_tree_eager_io_tg | 0.9943 | 0.9920–0.9966 | 0.9936 / 0.9950 |
| async_tree_eager_memoization | async_tree_eager_memoization | 0.9802 | 0.9772–0.9831 | 0.9790 / 0.9813 |
| async_tree_eager_memoization_tg | async_tree_eager_memoization_tg | 0.9800 | 0.9769–0.9832 | 0.9825 / 0.9776 |
| async_tree_eager_tg | async_tree_eager_tg | 0.9853 | 0.9842–0.9864 | 0.9807 / 0.9899 |
| async_tree_io | async_tree_io | 0.9846 | 0.9825–0.9867 | 0.9848 / 0.9843 |
| async_tree_io_tg | async_tree_io_tg | 0.9859 | 0.9848–0.9869 | 0.9850 / 0.9868 |
| async_tree_memoization | async_tree_memoization | 0.9924 | 0.9899–0.9950 | 0.9915 / 0.9934 |
| async_tree_memoization_tg | async_tree_memoization_tg | 0.9974 | 0.9913–1.0036 | 1.0007 / 0.9942 |
| async_tree_none | async_tree | 0.9951 | 0.9874–1.0029 | 0.9928 / 0.9974 |
| async_tree_none_tg | async_tree_tg | 1.0108 | 0.9999–1.0216 | 1.0033 / 1.0184 |
| base16_large | base64 | 0.8681 | 0.8657–0.8706 | 0.8712 / 0.8650 |
| base16_small | base64 | 0.9942 | 0.9921–0.9962 | 0.9931 / 0.9953 |
| base32_large | base64 | 1.0001 | 0.9996–1.0006 | 1.0006 / 0.9996 |
| base32_small | base64 | 1.0987 | 1.0965–1.1008 | 1.0971 / 1.1003 |
| base64_large | base64 | 1.0003 | 0.9970–1.0035 | 0.9999 / 1.0006 |
| base64_small | base64 | 1.0737 | 1.0720–1.0753 | 1.0750 / 1.0724 |
| base85_large | base64 | 1.0026 | 1.0009–1.0043 | 1.0014 / 1.0039 |
| base85_small | base64 | 1.0809 | 1.0796–1.0822 | 1.0801 / 1.0817 |
| bpe_tokeniser | bpe_tokeniser | 0.8501 | 0.8472–0.8530 | 0.8503 / 0.8498 |
| chameleon | chameleon | 0.9723 | 0.9651–0.9797 | 0.9628 / 0.9819 |
| chaos | chaos | 0.9242 | 0.9009–0.9492 | 0.8892 / 0.9606 |
| comprehensions | comprehensions | 1.0111 | 1.0082–1.0142 | 1.0137 / 1.0085 |
| connected_components | networkx_connected_components | 1.0080 | 1.0024–1.0135 | 0.9951 / 1.0211 |
| coroutines | coroutines | 1.0103 | 1.0071–1.0134 | 1.0141 / 1.0064 |
| coverage | coverage | 0.9990 | 0.9972–1.0010 | 0.9979 / 1.0001 |
| create_gc_cycles | gc_collect | 0.9806 | 0.9745–0.9869 | 0.9888 / 0.9725 |
| crypto_pyaes | crypto_pyaes | 0.9862 | 0.9829–0.9895 | 0.9823 / 0.9900 |
| deepcopy | deepcopy | 0.9874 | 0.9753–0.9998 | 0.9913 / 0.9836 |
| deepcopy_memo | deepcopy | 1.0359 | 1.0240–1.0472 | 1.0391 / 1.0327 |
| deepcopy_reduce | deepcopy | 0.9605 | 0.9584–0.9626 | 0.9576 / 0.9634 |
| deltablue | deltablue | 1.0196 | 1.0099–1.0296 | 1.0213 / 1.0179 |
| django_template | django_template | 0.9389 | 0.9063–0.9746 | 0.8920 / 0.9882 |
| docutils | docutils | 0.9572 | 0.9542–0.9606 | 0.9578 / 0.9567 |
| dulwich_log | dulwich_log | 1.0083 | 0.9955–1.0214 | 1.0159 / 1.0008 |
| fannkuch | fannkuch | 0.9081 | 0.9032–0.9131 | 0.9139 / 0.9024 |
| float | float | 1.0592 | 1.0533–1.0651 | 1.0647 / 1.0537 |
| gc_traversal | gc_traversal | 1.0489 | 1.0426–1.0553 | 1.0529 / 1.0449 |
| generators | generators | 0.9561 | 0.9496–0.9627 | 0.9622 / 0.9501 |
| genshi_text | genshi | 1.0781 | 1.0752–1.0813 | 1.0764 / 1.0798 |
| genshi_xml | genshi | 1.0526 | 1.0399–1.0655 | 1.0562 / 1.0489 |
| go | go | 1.0510 | 1.0411–1.0612 | 1.0513 / 1.0508 |
| hexiom | hexiom | 0.9638 | 0.9530–0.9750 | 0.9555 / 0.9722 |
| html5lib | html5lib | 0.8720 | 0.8620–0.8822 | 0.8815 / 0.8627 |
| json_dumps | json_dumps | 1.0174 | 1.0069–1.0285 | 1.0087 / 1.0263 |
| json_loads | json_loads | 0.9788 | 0.9749–0.9827 | 0.9841 / 0.9736 |
| logging_format | logging | 1.1265 | 1.1227–1.1302 | 1.1163 / 1.1367 |
| logging_silent | logging | 1.0554 | 1.0469–1.0640 | 1.0564 / 1.0544 |
| logging_simple | logging | 1.0969 | 1.0918–1.1020 | 1.0918 / 1.1020 |
| mako | mako | 0.9644 | 0.9617–0.9670 | 0.9673 / 0.9616 |
| many_optionals | argparse | 0.9674 | 0.9644–0.9705 | 0.9673 / 0.9676 |
| mdp | mdp | 0.9383 | 0.9334–0.9432 | 0.9379 / 0.9387 |
| meteor_contest | meteor_contest | 1.0096 | 1.0057–1.0136 | 1.0067 / 1.0126 |
| nbody | nbody | 0.9038 | 0.9021–0.9056 | 0.9088 / 0.8989 |
| nqueens | nqueens | 1.1067 | 1.1043–1.1092 | 1.1101 / 1.1034 |
| pathlib | pathlib | 1.0159 | 1.0042–1.0279 | 1.0172 / 1.0147 |
| pickle | pickle | 0.9861 | 0.9830–0.9892 | 0.9814 / 0.9908 |
| pickle_dict | pickle_dict | 0.9390 | 0.9313–0.9469 | 0.9358 / 0.9423 |
| pickle_list | pickle_list | 1.0113 | 1.0033–1.0193 | 1.0130 / 1.0095 |
| pickle_pure_python | pickle_pure_python | 0.9729 | 0.9709–0.9749 | 0.9737 / 0.9721 |
| pidigits | pidigits | 1.0055 | 1.0051–1.0058 | 1.0049 / 1.0061 |
| pprint_pformat | pprint | 1.0627 | 1.0583–1.0670 | 1.0585 / 1.0668 |
| pprint_safe_repr | pprint | 1.0468 | 1.0358–1.0579 | 1.0358 / 1.0579 |
| pyflate | pyflate | 1.0056 | 0.9944–1.0156 | 1.0155 / 0.9957 |
| python_startup | python_startup | 0.9932 | 0.9900–0.9964 | 0.9934 / 0.9930 |
| python_startup_no_site | python_startup_no_site | 1.0009 | 0.9941–1.0078 | 1.0083 / 0.9936 |
| raytrace | raytrace | 0.9275 | 0.9105–0.9454 | 0.9107 / 0.9447 |
| regex_compile | regex_compile | 1.0460 | 1.0428–1.0492 | 1.0399 / 1.0522 |
| regex_dna | regex_dna | 0.9716 | 0.9708–0.9723 | 0.9708 / 0.9723 |
| regex_effbot | regex_effbot | 0.9734 | 0.9694–0.9774 | 0.9665 / 0.9804 |
| regex_v8 | regex_v8 | 0.9455 | 0.9432–0.9479 | 0.9444 / 0.9467 |
| richards | richards | 1.2519 | 1.2414–1.2625 | 1.2435 / 1.2603 |
| richards_super | richards_super | 1.3603 | 1.3558–1.3649 | 1.3570 / 1.3637 |
| scimark_fft | scimark | 0.9746 | 0.9724–0.9769 | 0.9758 / 0.9735 |
| scimark_lu | scimark | 1.2477 | 1.2417–1.2538 | 1.2501 / 1.2453 |
| scimark_monte_carlo | scimark | 0.8901 | 0.8887–0.8914 | 0.8900 / 0.8902 |
| scimark_sor | scimark | 0.9672 | 0.9559–0.9789 | 0.9570 / 0.9775 |
| scimark_sparse_mat_mult | scimark | 0.9460 | 0.9428–0.9492 | 0.9517 / 0.9403 |
| shortest_path | networkx | 1.1010 | 1.0301–1.1680 | 1.0360 / 1.1701 |
| spectral_norm | spectral_norm | 0.6661 | 0.6571–0.6751 | 0.6725 / 0.6597 |
| sphinx | sphinx | 0.9795 | 0.9763–0.9826 | 0.9822 / 0.9768 |
| sqlalchemy_declarative | sqlalchemy_declarative | 0.8778 | 0.8750–0.8806 | 0.8790 / 0.8766 |
| sqlalchemy_imperative | sqlalchemy_imperative | 0.9802 | 0.9645–0.9960 | 1.0051 / 0.9559 |
| sqlglot_v2_normalize | sqlglot_v2 | 1.0433 | 1.0423–1.0443 | 1.0407 / 1.0460 |
| sqlglot_v2_optimize | sqlglot_v2_optimize | 1.0088 | 0.9949–1.0234 | 0.9978 / 1.0201 |
| sqlglot_v2_parse | sqlglot_v2_parse | 1.0066 | 1.0051–1.0081 | 1.0053 / 1.0079 |
| sqlglot_v2_transpile | sqlglot_v2_transpile | 1.0138 | 1.0100–1.0170 | 1.0067 / 1.0209 |
| sqlite_synth | sqlite_synth | 0.9846 | 0.9812–0.9880 | 0.9876 / 0.9816 |
| subparsers | argparse_subparsers | 0.9965 | 0.9952–0.9978 | 0.9976 / 0.9955 |
| sympy_expand | sympy | 1.0281 | 1.0206–1.0357 | 1.0284 / 1.0278 |
| sympy_integrate | sympy | 0.9501 | 0.9436–0.9566 | 0.9547 / 0.9454 |
| sympy_str | sympy | 0.9430 | 0.9376–0.9483 | 0.9486 / 0.9374 |
| sympy_sum | sympy | 0.9322 | 0.9269–0.9376 | 0.9319 / 0.9326 |
| telco | telco | 0.9943 | 0.9776–1.0113 | 1.0077 / 0.9812 |
| tomli_loads | tomli_loads | 0.9570 | 0.9493–0.9651 | 0.9481 / 0.9660 |
| typing_runtime_protocols | typing_runtime_protocols | 1.0112 | 1.0068–1.0156 | 1.0137 / 1.0087 |
| unpack_sequence | unpack_sequence | 0.5727 | 0.5708–0.5745 | 0.5728 / 0.5725 |
| unpickle | unpickle | 0.9787 | 0.9718–0.9855 | 0.9782 / 0.9791 |
| unpickle_list | unpickle_list | 1.0183 | 1.0085–1.0284 | 1.0126 / 1.0241 |
| unpickle_pure_python | unpickle_pure_python | 0.9641 | 0.9620–0.9663 | 0.9626 / 0.9656 |
| urlsafe_base64_small | base64 | 0.9759 | 0.9567–0.9959 | 0.9805 / 0.9714 |
| xdsl_constant_fold | xdsl | 0.9681 | 0.9612–0.9748 | 0.9619 / 0.9743 |
| xml_etree_generate | xml_etree | 0.8809 | 0.8794–0.8822 | 0.8830 / 0.8788 |
| xml_etree_iterparse | xml_etree | 0.9949 | 0.9909–0.9992 | 0.9957 / 0.9942 |
| xml_etree_parse | xml_etree | 0.9848 | 0.9815–0.9880 | 0.9794 / 0.9901 |
| xml_etree_process | xml_etree | 0.9339 | 0.9272–0.9408 | 0.9379 / 0.9299 |

## 実行失敗

以下は成功数・性能比・幾何平均へ含めない。元のログを保存している。

- `asyncio_tcp`: main/block 0 rc=1, candidate/block 0 rc=1, candidate/block 1 rc=1, main/block 1 rc=1.
  ログ例: `jit-artifacts/regressions-20260919/m22b-gil-rest-screen-0-asyncio_tcp-main.log`。
- `asyncio_tcp_ssl`: main/block 0 rc=1, candidate/block 0 rc=1, candidate/block 1 rc=1, main/block 1 rc=1.
  ログ例: `jit-artifacts/regressions-20260919/m22b-gil-rest-screen-0-asyncio_tcp_ssl-main.log`。
- `asyncio_websockets`: main/block 0 rc=1, candidate/block 0 rc=1, candidate/block 1 rc=1, main/block 1 rc=1.
  ログ例: `jit-artifacts/regressions-20260919/m22b-gil-rest-screen-0-asyncio_websockets-main.log`。
- `concurrent_imap`: main/block 0 rc=1, candidate/block 0 rc=1, candidate/block 1 rc=1, main/block 1 rc=1.
  ログ例: `jit-artifacts/regressions-20260919/m22b-gil-rest-screen-0-concurrent_imap-main.log`。
- `dask`: main/block 0 rc=1, candidate/block 0 rc=1, candidate/block 1 rc=1, main/block 1 rc=1.
  ログ例: `jit-artifacts/regressions-20260919/m22b-gil-rest-screen-0-dask-main.log`。
- `fastapi`: main/block 0 rc=1, candidate/block 0 rc=1, candidate/block 1 rc=1, main/block 1 rc=1.
  ログ例: `jit-artifacts/regressions-20260919/m22b-gil-rest-screen-0-fastapi-main.log`。
- `networkx_k_core`: main/block 0 rc=124, candidate/block 0 rc=124, candidate/block 1 rc=124, main/block 1 rc=124.
  ログ例: `jit-artifacts/regressions-20260919/m22b-gil-rest-screen-0-networkx_k_core-main.log`。
- `tornado_http`: main/block 0 rc=1, candidate/block 0 rc=1, candidate/block 1 rc=1, main/block 1 rc=1.
  ログ例: `jit-artifacts/regressions-20260919/m22b-gil-rest-screen-0-tornado_http-main.log`。

通信とプロセス同期のEPERMはsandbox制限で、main・候補とも発生。
fastapiは元の依存準備でpydantic-core/PyO3がPython 3.16を拒否したため未準備。
httpxだけを足して解決したとは扱わない。未準備groupもscreenへ含めたため失敗として記録した。
`networkx_k_core`は両側・両blockで15秒worker上限に達した。上限は延長していない。
通信・同期の6仕様のsandbox外再測定は別途追記する。

## 固定入力と監査

最初の14仕様の後、2to3のcommand metadataをharnessが扱えずKeyErrorで停止した。
14仕様56runを保存・identity監査後、metadata検証の分岐だけ修正して残る83仕様を再開した。
未記録だった2to3のmain JSONも保持するが、対応する比較がないため集計には使わない。
両区間のbinary、workload、bootstrapは同一で、両区間とも測定前後のidentity一致を確認した。
harness revisionは異なるため、2区間のstateを分けたまま保存している。

- main: `/home/methane/work/python/cpython-gc/jit-artifacts/regressions-20260919/method-main-gil-dev-build/python`
  SHA-256: `cafdcfa052a142b456095b69ec8f99c7a0fcac701403055bfaae587e0de770ea`
- candidate: `/home/methane/work/python/cpython-gc/jit-artifacts/regressions-20260919/m22b-gil-release-build/python`
  SHA-256: `85131c6be05bbfee337737f74247df56ad55f8ac0480480dccebb92c4c55b943`

生データ・全worker・集計JSON:

- `jit-artifacts/regressions-20260919/m22b-gil-all-screen-state.json`
- `jit-artifacts/regressions-20260919/m22b-gil-rest-screen-state.json`
- `jit-artifacts/regressions-20260919/m22b-gil-combined-analysis.json`
