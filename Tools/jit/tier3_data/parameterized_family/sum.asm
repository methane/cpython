
Tools/jit/tier3_data/parameterized_family/sum.bin:     file format binary


Disassembly of section .data:

0000000000000000 <.data>:
       0:	48 89 fb             	mov    %rdi,%rbx
       3:	4d 89 a7 30 01 00 00 	mov    %r12,0x130(%r15)
       a:	41 80 7c 24 22 00    	cmpb   $0x0,0x22(%r12)
      10:	74 05                	je     0x17
      12:	48 89 df             	mov    %rbx,%rdi
      15:	eb 35                	jmp    0x4c
      17:	48 83 ec 18          	sub    $0x18,%rsp
      1b:	4d 89 75 40          	mov    %r14,0x40(%r13)
      1f:	49 8b bf 38 01 00 00 	mov    0x138(%r15),%rdi
      26:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
      2b:	48 89 74 24 08       	mov    %rsi,0x8(%rsp)
      30:	ff 15 75 09 00 00    	call   *0x975(%rip)        # 0x9ab
      36:	48 89 df             	mov    %rbx,%rdi
      39:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
      3e:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
      43:	48 83 c4 18          	add    $0x18,%rsp
      47:	e9 73 06 00 00       	jmp    0x6bf
      4c:	41 c6 44 24 24 00    	movb   $0x0,0x24(%r12)
      52:	48 b8 be 3d ea 10 ed 	movabs $0x7fed10ea3dbe,%rax
      59:	7f 00 00
      5c:	49 89 45 38          	mov    %rax,0x38(%r13)
      60:	4d 89 75 40          	mov    %r14,0x40(%r13)
      64:	49 8b 47 18          	mov    0x18(%r15),%rax
      68:	84 c0                	test   %al,%al
      6a:	74 3b                	je     0xa7
      6c:	48 83 ec 18          	sub    $0x18,%rsp
      70:	48 89 7c 24 10       	mov    %rdi,0x10(%rsp)
      75:	4c 89 ff             	mov    %r15,%rdi
      78:	4c 89 64 24 08       	mov    %r12,0x8(%rsp)
      7d:	49 89 d4             	mov    %rdx,%r12
      80:	48 89 f3             	mov    %rsi,%rbx
      83:	ff 15 0a 09 00 00    	call   *0x90a(%rip)        # 0x993
      89:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
      8e:	4c 89 e2             	mov    %r12,%rdx
      91:	4c 8b 64 24 08       	mov    0x8(%rsp),%r12
      96:	85 c0                	test   %eax,%eax
      98:	48 8d 64 24 18       	lea    0x18(%rsp),%rsp
      9d:	74 08                	je     0xa7
      9f:	48 89 de             	mov    %rbx,%rsi
      a2:	e9 5b 06 00 00       	jmp    0x702
      a7:	31 ff                	xor    %edi,%edi
      a9:	31 f6                	xor    %esi,%esi
      ab:	31 d2                	xor    %edx,%edx
      ad:	41 80 7c 24 22 00    	cmpb   $0x0,0x22(%r12)
      b3:	0f 84 7d 06 00 00    	je     0x736
      b9:	49 8b 46 f0          	mov    -0x10(%r14),%rax
      bd:	48 89 c1             	mov    %rax,%rcx
      c0:	48 83 e1 fe          	and    $0xfffffffffffffffe,%rcx
      c4:	49 b8 20 ec 7e bf 69 	movabs $0x5569bf7eec20,%r8
      cb:	55 00 00
      ce:	4c 39 41 08          	cmp    %r8,0x8(%rcx)
      d2:	0f 85 a1 06 00 00    	jne    0x779
      d8:	49 8b 76 f8          	mov    -0x8(%r14),%rsi
      dc:	49 83 c6 f0          	add    $0xfffffffffffffff0,%r14
      e0:	48 89 c7             	mov    %rax,%rdi
      e3:	48 89 f8             	mov    %rdi,%rax
      e6:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
      ea:	48 83 78 20 00       	cmpq   $0x0,0x20(%rax)
      ef:	0f 8e a9 06 00 00    	jle    0x79e
      f5:	48 83 ec 78          	sub    $0x78,%rsp
      f9:	49 89 f8             	mov    %rdi,%r8
      fc:	4d 89 f9             	mov    %r15,%r9
      ff:	48 b8 23 00 00 00 00 	movabs $0x23,%rax
     106:	00 00 00
     109:	44 0f b7 f8          	movzwl %ax,%r15d
     10d:	41 c1 ef 04          	shr    $0x4,%r15d
     111:	48 89 fb             	mov    %rdi,%rbx
     114:	48 83 e3 fe          	and    $0xfffffffffffffffe,%rbx
     118:	4b 8b 7c fd 50       	mov    0x50(%r13,%r15,8),%rdi
     11d:	c7 44 24 5c 00 00 00 	movl   $0x0,0x5c(%rsp)
     124:	00
     125:	48 b8 20 ec 7e bf 69 	movabs $0x5569bf7eec20,%rax
     12c:	55 00 00
     12f:	48 39 43 08          	cmp    %rax,0x8(%rbx)
     133:	0f 85 cb 03 00 00    	jne    0x504
     139:	48 83 e7 fe          	and    $0xfffffffffffffffe,%rdi
     13d:	48 b8 00 7c 7e bf 69 	movabs $0x5569bf7e7c00,%rax
     144:	55 00 00
     147:	48 39 47 08          	cmp    %rax,0x8(%rdi)
     14b:	0f 85 b3 03 00 00    	jne    0x504
     151:	4c 89 64 24 30       	mov    %r12,0x30(%rsp)
     156:	48 89 54 24 48       	mov    %rdx,0x48(%rsp)
     15b:	4c 89 4c 24 18       	mov    %r9,0x18(%rsp)
     160:	4c 89 44 24 20       	mov    %r8,0x20(%rsp)
     165:	4d 89 06             	mov    %r8,(%r14)
     168:	48 89 74 24 50       	mov    %rsi,0x50(%rsp)
     16d:	49 89 76 08          	mov    %rsi,0x8(%r14)
     171:	4c 89 74 24 40       	mov    %r14,0x40(%rsp)
     176:	49 83 c6 10          	add    $0x10,%r14
     17a:	4c 89 6c 24 10       	mov    %r13,0x10(%rsp)
     17f:	4d 89 75 40          	mov    %r14,0x40(%r13)
     183:	48 8d 74 24 5c       	lea    0x5c(%rsp),%rsi
     188:	ff 15 25 08 00 00    	call   *0x825(%rip)        # 0x9b3
     18e:	49 89 c4             	mov    %rax,%r12
     191:	48 83 f8 ff          	cmp    $0xffffffffffffffff,%rax
     195:	0f 84 a3 00 00 00    	je     0x23e
     19b:	4d 89 e3             	mov    %r12,%r11
     19e:	4c 89 74 24 70       	mov    %r14,0x70(%rsp)
     1a3:	83 7c 24 5c 00       	cmpl   $0x0,0x5c(%rsp)
     1a8:	48 8b 74 24 50       	mov    0x50(%rsp),%rsi
     1ad:	4c 8b 44 24 20       	mov    0x20(%rsp),%r8
     1b2:	4c 8b 4c 24 18       	mov    0x18(%rsp),%r9
     1b7:	4c 8b 64 24 30       	mov    0x30(%rsp),%r12
     1bc:	4c 8b 74 24 40       	mov    0x40(%rsp),%r14
     1c1:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     1c6:	0f 85 38 03 00 00    	jne    0x504
     1cc:	48 8b 53 20          	mov    0x20(%rbx),%rdx
     1d0:	48 83 fa 02          	cmp    $0x2,%rdx
     1d4:	0f 8c 2a 03 00 00    	jl     0x504
     1da:	49 8b 45 00          	mov    0x0(%r13),%rax
     1de:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     1e2:	4c 8b 90 a8 00 00 00 	mov    0xa8(%rax),%r10
     1e9:	48 8b 43 10          	mov    0x10(%rbx),%rax
     1ed:	48 89 44 24 68       	mov    %rax,0x68(%rsp)
     1f2:	41 8a 4c 24 22       	mov    0x22(%r12),%cl
     1f7:	84 c9                	test   %cl,%cl
     1f9:	40 0f 94 c7          	sete   %dil
     1fd:	49 8b 41 18          	mov    0x18(%r9),%rax
     201:	4c 89 54 24 28       	mov    %r10,0x28(%rsp)
     206:	4c 39 d0             	cmp    %r10,%rax
     209:	0f 95 c0             	setne  %al
     20c:	41 89 c2             	mov    %eax,%r10d
     20f:	40 08 f8             	or     %dil,%al
     212:	a8 01                	test   $0x1,%al
     214:	74 5e                	je     0x274
     216:	b8 01 00 00 00       	mov    $0x1,%eax
     21b:	48 c7 44 24 28 00 00 	movq   $0x0,0x28(%rsp)
     222:	00 00
     224:	48 c7 44 24 60 00 00 	movq   $0x0,0x60(%rsp)
     22b:	00 00
     22d:	48 c7 44 24 38 00 00 	movq   $0x0,0x38(%rsp)
     234:	00 00
     236:	44 89 d2             	mov    %r10d,%edx
     239:	e9 18 01 00 00       	jmp    0x356
     23e:	ff 15 77 07 00 00    	call   *0x777(%rip)        # 0x9bb
     244:	48 85 c0             	test   %rax,%rax
     247:	0f 84 4e ff ff ff    	je     0x19b
     24d:	4c 8b 64 24 30       	mov    0x30(%rsp),%r12
     252:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     257:	4c 8b 7c 24 18       	mov    0x18(%rsp),%r15
     25c:	48 8b 7c 24 20       	mov    0x20(%rsp),%rdi
     261:	48 8b 74 24 50       	mov    0x50(%rsp),%rsi
     266:	48 8b 54 24 48       	mov    0x48(%rsp),%rdx
     26b:	48 83 c4 78          	add    $0x78,%rsp
     26f:	e9 aa 05 00 00       	jmp    0x81e
     274:	89 7c 24 0c          	mov    %edi,0xc(%rsp)
     278:	4c 8d 42 ff          	lea    -0x1(%rdx),%r8
     27c:	48 83 c2 fe          	add    $0xfffffffffffffffe,%rdx
     280:	b8 01 00 00 00       	mov    $0x1,%eax
     285:	45 31 f6             	xor    %r14d,%r14d
     288:	4c 89 df             	mov    %r11,%rdi
     28b:	4d 89 d9             	mov    %r11,%r9
     28e:	45 31 d2             	xor    %r10d,%r10d
     291:	4c 8b 6c 24 68       	mov    0x68(%rsp),%r13
     296:	4c 01 ef             	add    %r13,%rdi
     299:	41 0f 90 c4          	seto   %r12b
     29d:	70 72                	jo     0x311
     29f:	49 89 fb             	mov    %rdi,%r11
     2a2:	4c 8b 4b 18          	mov    0x18(%rbx),%r9
     2a6:	4c 89 6c 24 60       	mov    %r13,0x60(%rsp)
     2ab:	4d 01 e9             	add    %r13,%r9
     2ae:	4c 89 4c 24 68       	mov    %r9,0x68(%rsp)
     2b3:	4c 39 f2             	cmp    %r14,%rdx
     2b6:	74 74                	je     0x32c
     2b8:	4c 8b 4c 24 18       	mov    0x18(%rsp),%r9
     2bd:	4d 8b 49 18          	mov    0x18(%r9),%r9
     2c1:	49 ff c6             	inc    %r14
     2c4:	4c 3b 4c 24 28       	cmp    0x28(%rsp),%r9
     2c9:	41 0f 95 c5          	setne  %r13b
     2cd:	75 12                	jne    0x2e1
     2cf:	4c 89 df             	mov    %r11,%rdi
     2d2:	48 ff c0             	inc    %rax
     2d5:	4d 89 d9             	mov    %r11,%r9
     2d8:	4c 8b 54 24 60       	mov    0x60(%rsp),%r10
     2dd:	84 c9                	test   %cl,%cl
     2df:	75 b0                	jne    0x291
     2e1:	4c 89 64 24 38       	mov    %r12,0x38(%rsp)
     2e6:	4c 89 74 24 28       	mov    %r14,0x28(%rsp)
     2eb:	49 8d 46 01          	lea    0x1(%r14),%rax
     2ef:	4c 8b 44 24 20       	mov    0x20(%rsp),%r8
     2f4:	4c 8b 4c 24 18       	mov    0x18(%rsp),%r9
     2f9:	4c 8b 64 24 30       	mov    0x30(%rsp),%r12
     2fe:	4c 8b 74 24 40       	mov    0x40(%rsp),%r14
     303:	44 89 ea             	mov    %r13d,%edx
     306:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     30b:	8b 7c 24 0c          	mov    0xc(%rsp),%edi
     30f:	eb 45                	jmp    0x356
     311:	4c 89 64 24 38       	mov    %r12,0x38(%rsp)
     316:	4c 89 74 24 28       	mov    %r14,0x28(%rsp)
     31b:	31 d2                	xor    %edx,%edx
     31d:	4c 89 6c 24 68       	mov    %r13,0x68(%rsp)
     322:	4d 89 cb             	mov    %r9,%r11
     325:	4c 89 54 24 60       	mov    %r10,0x60(%rsp)
     32a:	eb 0f                	jmp    0x33b
     32c:	4c 89 64 24 38       	mov    %r12,0x38(%rsp)
     331:	31 d2                	xor    %edx,%edx
     333:	4c 89 c0             	mov    %r8,%rax
     336:	4c 89 44 24 28       	mov    %r8,0x28(%rsp)
     33b:	31 ff                	xor    %edi,%edi
     33d:	4c 8b 44 24 20       	mov    0x20(%rsp),%r8
     342:	4c 8b 4c 24 18       	mov    0x18(%rsp),%r9
     347:	4c 8b 64 24 30       	mov    0x30(%rsp),%r12
     34c:	4c 8b 74 24 40       	mov    0x40(%rsp),%r14
     351:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     356:	40 08 fa             	or     %dil,%dl
     359:	49 01 84 24 c0 00 00 	add    %rax,0xc0(%r12)
     360:	00
     361:	89 54 24 0c          	mov    %edx,0xc(%rsp)
     365:	f6 c2 01             	test   $0x1,%dl
     368:	74 08                	je     0x372
     36a:	49 ff 84 24 c8 00 00 	incq   0xc8(%r12)
     371:	00
     372:	48 83 7c 24 28 00    	cmpq   $0x0,0x28(%rsp)
     378:	0f 84 0b 01 00 00    	je     0x489
     37e:	4d 89 06             	mov    %r8,(%r14)
     381:	49 89 76 08          	mov    %rsi,0x8(%r14)
     385:	4c 8b 74 24 70       	mov    0x70(%rsp),%r14
     38a:	4d 89 75 40          	mov    %r14,0x40(%r13)
     38e:	4c 89 df             	mov    %r11,%rdi
     391:	ff 15 2c 06 00 00    	call   *0x62c(%rip)        # 0x9c3
     397:	48 85 c0             	test   %rax,%rax
     39a:	0f 84 ad fe ff ff    	je     0x24d
     3a0:	49 89 c4             	mov    %rax,%r12
     3a3:	48 8b 7c 24 60       	mov    0x60(%rsp),%rdi
     3a8:	ff 15 f5 05 00 00    	call   *0x5f5(%rip)        # 0x9a3
     3ae:	48 85 c0             	test   %rax,%rax
     3b1:	0f 84 fc 00 00 00    	je     0x4b3
     3b7:	48 b9 23 00 00 00 00 	movabs $0x23,%rcx
     3be:	00 00 00
     3c1:	83 e1 0f             	and    $0xf,%ecx
     3c4:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     3c9:	4b 8b 7c fd 50       	mov    0x50(%r13,%r15,8),%rdi
     3ce:	89 c9                	mov    %ecx,%ecx
     3d0:	4c 89 e6             	mov    %r12,%rsi
     3d3:	4d 8b 64 cd 50       	mov    0x50(%r13,%rcx,8),%r12
     3d8:	0f b7 56 06          	movzwl 0x6(%rsi),%edx
     3dc:	83 e2 01             	and    $0x1,%edx
     3df:	48 09 f2             	or     %rsi,%rdx
     3e2:	4b 89 54 fd 50       	mov    %rdx,0x50(%r13,%r15,8)
     3e7:	0f b7 50 06          	movzwl 0x6(%rax),%edx
     3eb:	83 e2 01             	and    $0x1,%edx
     3ee:	48 09 c2             	or     %rax,%rdx
     3f1:	49 89 54 cd 50       	mov    %rdx,0x50(%r13,%rcx,8)
     3f6:	48 8b 44 24 68       	mov    0x68(%rsp),%rax
     3fb:	48 89 43 10          	mov    %rax,0x10(%rbx)
     3ff:	4c 8b 74 24 28       	mov    0x28(%rsp),%r14
     404:	4c 29 73 20          	sub    %r14,0x20(%rbx)
     408:	40 f6 c7 01          	test   $0x1,%dil
     40c:	75 0f                	jne    0x41d
     40e:	ff 0f                	decl   (%rdi)
     410:	75 0b                	jne    0x41d
     412:	ff 15 73 05 00 00    	call   *0x573(%rip)        # 0x98b
     418:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     41d:	41 f6 c4 01          	test   $0x1,%r12b
     421:	75 14                	jne    0x437
     423:	41 ff 0c 24          	decl   (%r12)
     427:	75 0e                	jne    0x437
     429:	4c 89 e7             	mov    %r12,%rdi
     42c:	ff 15 59 05 00 00    	call   *0x559(%rip)        # 0x98b
     432:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     437:	4c 8b 64 24 30       	mov    0x30(%rsp),%r12
     43c:	49 ff 84 24 b0 00 00 	incq   0xb0(%r12)
     443:	00
     444:	4d 01 b4 24 b8 00 00 	add    %r14,0xb8(%r12)
     44b:	00
     44c:	f6 44 24 0c 01       	testb  $0x1,0xc(%rsp)
     451:	0f 84 82 00 00 00    	je     0x4d9
     457:	49 ff 84 24 e0 00 00 	incq   0xe0(%r12)
     45e:	00
     45f:	80 7c 24 38 00       	cmpb   $0x0,0x38(%rsp)
     464:	48 8b 74 24 50       	mov    0x50(%rsp),%rsi
     469:	4c 8b 44 24 20       	mov    0x20(%rsp),%r8
     46e:	4c 8b 4c 24 18       	mov    0x18(%rsp),%r9
     473:	48 8b 54 24 48       	mov    0x48(%rsp),%rdx
     478:	4c 8b 74 24 40       	mov    0x40(%rsp),%r14
     47d:	74 25                	je     0x4a4
     47f:	49 ff 84 24 d0 00 00 	incq   0xd0(%r12)
     486:	00
     487:	eb 1b                	jmp    0x4a4
     489:	80 7c 24 38 00       	cmpb   $0x0,0x38(%rsp)
     48e:	74 08                	je     0x498
     490:	49 ff 84 24 d0 00 00 	incq   0xd0(%r12)
     497:	00
     498:	f6 44 24 0c 01       	testb  $0x1,0xc(%rsp)
     49d:	48 8b 54 24 48       	mov    0x48(%rsp),%rdx
     4a2:	74 60                	je     0x504
     4a4:	4d 89 cf             	mov    %r9,%r15
     4a7:	4c 89 c7             	mov    %r8,%rdi
     4aa:	48 83 c4 78          	add    $0x78,%rsp
     4ae:	e9 1b 03 00 00       	jmp    0x7ce
     4b3:	41 8b 04 24          	mov    (%r12),%eax
     4b7:	85 c0                	test   %eax,%eax
     4b9:	0f 88 8e fd ff ff    	js     0x24d
     4bf:	ff c8                	dec    %eax
     4c1:	41 89 04 24          	mov    %eax,(%r12)
     4c5:	0f 85 82 fd ff ff    	jne    0x24d
     4cb:	4c 89 e7             	mov    %r12,%rdi
     4ce:	ff 15 b7 04 00 00    	call   *0x4b7(%rip)        # 0x98b
     4d4:	e9 74 fd ff ff       	jmp    0x24d
     4d9:	49 ff 84 24 d8 00 00 	incq   0xd8(%r12)
     4e0:	00
     4e1:	80 7c 24 38 00       	cmpb   $0x0,0x38(%rsp)
     4e6:	48 8b 74 24 50       	mov    0x50(%rsp),%rsi
     4eb:	4c 8b 44 24 20       	mov    0x20(%rsp),%r8
     4f0:	4c 8b 4c 24 18       	mov    0x18(%rsp),%r9
     4f5:	4c 8b 74 24 40       	mov    0x40(%rsp),%r14
     4fa:	74 08                	je     0x504
     4fc:	49 ff 84 24 d0 00 00 	incq   0xd0(%r12)
     503:	00
     504:	4d 89 cf             	mov    %r9,%r15
     507:	4c 89 c7             	mov    %r8,%rdi
     50a:	31 d2                	xor    %edx,%edx
     50c:	48 83 c4 78          	add    $0x78,%rsp
     510:	48 83 ec 18          	sub    $0x18,%rsp
     514:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
     519:	48 89 74 24 08       	mov    %rsi,0x8(%rsp)
     51e:	48 89 fb             	mov    %rdi,%rbx
     521:	48 89 f8             	mov    %rdi,%rax
     524:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     528:	48 8b 78 10          	mov    0x10(%rax),%rdi
     52c:	48 8b 48 18          	mov    0x18(%rax),%rcx
     530:	48 01 f9             	add    %rdi,%rcx
     533:	48 89 48 10          	mov    %rcx,0x10(%rax)
     537:	48 ff 48 20          	decq   0x20(%rax)
     53b:	ff 15 62 04 00 00    	call   *0x462(%rip)        # 0x9a3
     541:	48 85 c0             	test   %rax,%rax
     544:	74 18                	je     0x55e
     546:	0f b7 50 06          	movzwl 0x6(%rax),%edx
     54a:	83 e2 01             	and    $0x1,%edx
     54d:	48 09 c2             	or     %rax,%rdx
     550:	48 89 df             	mov    %rbx,%rdi
     553:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     558:	48 83 c4 18          	add    $0x18,%rsp
     55c:	eb 21                	jmp    0x57f
     55e:	49 89 1e             	mov    %rbx,(%r14)
     561:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     566:	49 89 76 08          	mov    %rsi,0x8(%r14)
     56a:	49 83 c6 10          	add    $0x10,%r14
     56e:	48 89 df             	mov    %rbx,%rdi
     571:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
     576:	48 83 c4 18          	add    $0x18,%rsp
     57a:	e9 d3 02 00 00       	jmp    0x852
     57f:	48 b8 ac 3d ea 10 ed 	movabs $0x7fed10ea3dac,%rax
     586:	7f 00 00
     589:	49 89 45 38          	mov    %rax,0x38(%r13)
     58d:	49 8b 45 68          	mov    0x68(%r13),%rax
     591:	49 89 55 68          	mov    %rdx,0x68(%r13)
     595:	48 89 c2             	mov    %rax,%rdx
     598:	49 89 3e             	mov    %rdi,(%r14)
     59b:	49 89 76 08          	mov    %rsi,0x8(%r14)
     59f:	49 83 c6 10          	add    $0x10,%r14
     5a3:	48 89 d7             	mov    %rdx,%rdi
     5a6:	4d 89 75 40          	mov    %r14,0x40(%r13)
     5aa:	40 f6 c7 01          	test   $0x1,%dil
     5ae:	75 0f                	jne    0x5bf
     5b0:	ff 0f                	decl   (%rdi)
     5b2:	75 0b                	jne    0x5bf
     5b4:	50                   	push   %rax
     5b5:	ff 15 d0 03 00 00    	call   *0x3d0(%rip)        # 0x98b
     5bb:	48 83 c4 08          	add    $0x8,%rsp
     5bf:	31 ff                	xor    %edi,%edi
     5c1:	31 f6                	xor    %esi,%esi
     5c3:	31 d2                	xor    %edx,%edx
     5c5:	41 80 7c 24 22 00    	cmpb   $0x0,0x22(%r12)
     5cb:	0f 84 b5 02 00 00    	je     0x886
     5d1:	49 8b 7d 60          	mov    0x60(%r13),%rdi
     5d5:	48 83 cf 01          	or     $0x1,%rdi
     5d9:	49 8b 75 68          	mov    0x68(%r13),%rsi
     5dd:	48 83 ce 01          	or     $0x1,%rsi
     5e1:	48 b8 b0 3d ea 10 ed 	movabs $0x7fed10ea3db0,%rax
     5e8:	7f 00 00
     5eb:	49 89 45 38          	mov    %rax,0x38(%r13)
     5ef:	48 83 ec 18          	sub    $0x18,%rsp
     5f3:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
     5f8:	48 89 f0             	mov    %rsi,%rax
     5fb:	48 89 fb             	mov    %rdi,%rbx
     5fe:	4c 89 3c 24          	mov    %r15,(%rsp)
     602:	48 83 e7 fe          	and    $0xfffffffffffffffe,%rdi
     606:	48 83 e6 fe          	and    $0xfffffffffffffffe,%rsi
     60a:	49 89 1e             	mov    %rbx,(%r14)
     60d:	48 89 44 24 08       	mov    %rax,0x8(%rsp)
     612:	49 89 46 08          	mov    %rax,0x8(%r14)
     616:	4d 8d 7e 10          	lea    0x10(%r14),%r15
     61a:	4d 89 7d 40          	mov    %r15,0x40(%r13)
     61e:	48 b8 0d 00 00 00 00 	movabs $0xd,%rax
     625:	00 00 00
     628:	0f b7 c0             	movzwl %ax,%eax
     62b:	48 b9 a0 55 79 bf 69 	movabs $0x5569bf7955a0,%rcx
     632:	55 00 00
     635:	ff 14 c1             	call   *(%rcx,%rax,8)
     638:	48 85 c0             	test   %rax,%rax
     63b:	74 1c                	je     0x659
     63d:	0f b7 78 06          	movzwl 0x6(%rax),%edi
     641:	83 e7 01             	and    $0x1,%edi
     644:	48 09 c7             	or     %rax,%rdi
     647:	4c 8b 3c 24          	mov    (%rsp),%r15
     64b:	48 89 de             	mov    %rbx,%rsi
     64e:	48 8b 54 24 08       	mov    0x8(%rsp),%rdx
     653:	48 83 c4 18          	add    $0x18,%rsp
     657:	eb 1d                	jmp    0x676
     659:	4d 89 fe             	mov    %r15,%r14
     65c:	4c 8b 3c 24          	mov    (%rsp),%r15
     660:	48 89 df             	mov    %rbx,%rdi
     663:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     668:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
     66d:	48 83 c4 18          	add    $0x18,%rsp
     671:	e9 53 02 00 00       	jmp    0x8c9
     676:	41 80 7c 24 22 00    	cmpb   $0x0,0x22(%r12)
     67c:	0f 84 7b 02 00 00    	je     0x8fd
     682:	48 b8 bc 3d ea 10 ed 	movabs $0x7fed10ea3dbc,%rax
     689:	7f 00 00
     68c:	49 89 45 38          	mov    %rax,0x38(%r13)
     690:	49 8b 45 60          	mov    0x60(%r13),%rax
     694:	49 89 7d 60          	mov    %rdi,0x60(%r13)
     698:	48 89 c7             	mov    %rax,%rdi
     69b:	4d 89 75 40          	mov    %r14,0x40(%r13)
     69f:	40 f6 c7 01          	test   $0x1,%dil
     6a3:	75 0f                	jne    0x6b4
     6a5:	ff 0f                	decl   (%rdi)
     6a7:	75 0b                	jne    0x6b4
     6a9:	50                   	push   %rax
     6aa:	ff 15 db 02 00 00    	call   *0x2db(%rip)        # 0x98b
     6b0:	48 83 c4 08          	add    $0x8,%rsp
     6b4:	31 ff                	xor    %edi,%edi
     6b6:	31 f6                	xor    %esi,%esi
     6b8:	31 d2                	xor    %edx,%edx
     6ba:	e9 8d f9 ff ff       	jmp    0x4c
     6bf:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     6c6:	00 00 00 00
     6ca:	4d 89 75 40          	mov    %r14,0x40(%r13)
     6ce:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     6d3:	75 0e                	jne    0x6e3
     6d5:	48 b8 c0 a9 7f bf 69 	movabs $0x5569bf7fa9c0,%rax
     6dc:	55 00 00
     6df:	48 8b 00             	mov    (%rax),%rax
     6e2:	c3                   	ret
     6e3:	49 8b 45 00          	mov    0x0(%r13),%rax
     6e7:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     6eb:	48 b9 1b 00 00 00 00 	movabs $0x1b,%rcx
     6f2:	00 00 00
     6f5:	89 c9                	mov    %ecx,%ecx
     6f7:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     6fb:	48 05 c8 00 00 00    	add    $0xc8,%rax
     701:	c3                   	ret
     702:	49 8b 45 00          	mov    0x0(%r13),%rax
     706:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     70a:	48 b9 1b 00 00 00 00 	movabs $0x1b,%rcx
     711:	00 00 00
     714:	89 c9                	mov    %ecx,%ecx
     716:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     71a:	48 05 c8 00 00 00    	add    $0xc8,%rax
     720:	49 89 45 38          	mov    %rax,0x38(%r13)
     724:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     72b:	00 00 00 00
     72f:	4d 89 75 40          	mov    %r14,0x40(%r13)
     733:	31 c0                	xor    %eax,%eax
     735:	c3                   	ret
     736:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     73d:	00 00 00 00
     741:	4d 89 75 40          	mov    %r14,0x40(%r13)
     745:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     74a:	75 0e                	jne    0x75a
     74c:	48 b8 c0 a9 7f bf 69 	movabs $0x5569bf7fa9c0,%rax
     753:	55 00 00
     756:	48 8b 00             	mov    (%rax),%rax
     759:	c3                   	ret
     75a:	49 8b 45 00          	mov    0x0(%r13),%rax
     75e:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     762:	48 b9 10 00 00 00 00 	movabs $0x10,%rcx
     769:	00 00 00
     76c:	89 c9                	mov    %ecx,%ecx
     76e:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     772:	48 05 c8 00 00 00    	add    $0xc8,%rax
     778:	c3                   	ret
     779:	48 b8 d8 21 7c d1 69 	movabs $0x5569d17c21d8,%rax
     780:	55 00 00
     783:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     78a:	48 b8 e0 21 7c d1 69 	movabs $0x5569d17c21e0,%rax
     791:	55 00 00
     794:	4c 8b 20             	mov    (%rax),%r12
     797:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     79c:	ff e0                	jmp    *%rax
     79e:	48 b8 e8 21 7c d1 69 	movabs $0x5569d17c21e8,%rax
     7a5:	55 00 00
     7a8:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     7af:	49 89 3e             	mov    %rdi,(%r14)
     7b2:	49 89 76 08          	mov    %rsi,0x8(%r14)
     7b6:	49 83 c6 10          	add    $0x10,%r14
     7ba:	48 b8 f0 21 7c d1 69 	movabs $0x5569d17c21f0,%rax
     7c1:	55 00 00
     7c4:	4c 8b 20             	mov    (%rax),%r12
     7c7:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     7cc:	ff e0                	jmp    *%rax
     7ce:	50                   	push   %rax
     7cf:	49 89 3e             	mov    %rdi,(%r14)
     7d2:	49 89 76 08          	mov    %rsi,0x8(%r14)
     7d6:	49 83 c6 10          	add    $0x10,%r14
     7da:	4d 89 75 40          	mov    %r14,0x40(%r13)
     7de:	4c 89 ff             	mov    %r15,%rdi
     7e1:	ff 15 ac 01 00 00    	call   *0x1ac(%rip)        # 0x993
     7e7:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     7ee:	00 00 00 00
     7f2:	4d 89 75 40          	mov    %r14,0x40(%r13)
     7f6:	85 c0                	test   %eax,%eax
     7f8:	74 04                	je     0x7fe
     7fa:	31 c0                	xor    %eax,%eax
     7fc:	eb 1e                	jmp    0x81c
     7fe:	49 8b 45 00          	mov    0x0(%r13),%rax
     802:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     806:	48 b9 1b 00 00 00 00 	movabs $0x1b,%rcx
     80d:	00 00 00
     810:	89 c9                	mov    %ecx,%ecx
     812:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     816:	48 05 c8 00 00 00    	add    $0xc8,%rax
     81c:	59                   	pop    %rcx
     81d:	c3                   	ret
     81e:	49 8b 45 00          	mov    0x0(%r13),%rax
     822:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     826:	48 b9 14 00 00 00 00 	movabs $0x14,%rcx
     82d:	00 00 00
     830:	89 c9                	mov    %ecx,%ecx
     832:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     836:	48 05 c8 00 00 00    	add    $0xc8,%rax
     83c:	49 89 45 38          	mov    %rax,0x38(%r13)
     840:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     847:	00 00 00 00
     84b:	4d 89 75 40          	mov    %r14,0x40(%r13)
     84f:	31 c0                	xor    %eax,%eax
     851:	c3                   	ret
     852:	49 8b 45 00          	mov    0x0(%r13),%rax
     856:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     85a:	48 b9 10 00 00 00 00 	movabs $0x10,%rcx
     861:	00 00 00
     864:	89 c9                	mov    %ecx,%ecx
     866:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     86a:	48 05 c8 00 00 00    	add    $0xc8,%rax
     870:	49 89 45 38          	mov    %rax,0x38(%r13)
     874:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     87b:	00 00 00 00
     87f:	4d 89 75 40          	mov    %r14,0x40(%r13)
     883:	31 c0                	xor    %eax,%eax
     885:	c3                   	ret
     886:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     88d:	00 00 00 00
     891:	4d 89 75 40          	mov    %r14,0x40(%r13)
     895:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     89a:	75 0e                	jne    0x8aa
     89c:	48 b8 c0 a9 7f bf 69 	movabs $0x5569bf7fa9c0,%rax
     8a3:	55 00 00
     8a6:	48 8b 00             	mov    (%rax),%rax
     8a9:	c3                   	ret
     8aa:	49 8b 45 00          	mov    0x0(%r13),%rax
     8ae:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     8b2:	48 b9 13 00 00 00 00 	movabs $0x13,%rcx
     8b9:	00 00 00
     8bc:	89 c9                	mov    %ecx,%ecx
     8be:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     8c2:	48 05 c8 00 00 00    	add    $0xc8,%rax
     8c8:	c3                   	ret
     8c9:	49 8b 45 00          	mov    0x0(%r13),%rax
     8cd:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     8d1:	48 b9 14 00 00 00 00 	movabs $0x14,%rcx
     8d8:	00 00 00
     8db:	89 c9                	mov    %ecx,%ecx
     8dd:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     8e1:	48 05 c8 00 00 00    	add    $0xc8,%rax
     8e7:	49 89 45 38          	mov    %rax,0x38(%r13)
     8eb:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     8f2:	00 00 00 00
     8f6:	4d 89 75 40          	mov    %r14,0x40(%r13)
     8fa:	31 c0                	xor    %eax,%eax
     8fc:	c3                   	ret
     8fd:	49 89 3e             	mov    %rdi,(%r14)
     900:	49 83 c6 08          	add    $0x8,%r14
     904:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     90b:	00 00 00 00
     90f:	4d 89 75 40          	mov    %r14,0x40(%r13)
     913:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     918:	75 0e                	jne    0x928
     91a:	48 b8 c0 a9 7f bf 69 	movabs $0x5569bf7fa9c0,%rax
     921:	55 00 00
     924:	48 8b 00             	mov    (%rax),%rax
     927:	c3                   	ret
     928:	49 8b 45 00          	mov    0x0(%r13),%rax
     92c:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     930:	48 b9 1a 00 00 00 00 	movabs $0x1a,%rcx
     937:	00 00 00
     93a:	89 c9                	mov    %ecx,%ecx
     93c:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     940:	48 05 c8 00 00 00    	add    $0xc8,%rax
     946:	c3                   	ret
     947:	50                   	push   %rax
     948:	48 bf 63 e9 a8 10 ed 	movabs $0x7fed10a8e963,%rdi
     94f:	7f 00 00
     952:	48 be 6e e9 a8 10 ed 	movabs $0x7fed10a8e96e,%rsi
     959:	7f 00 00
     95c:	ff 15 39 00 00 00    	call   *0x39(%rip)        # 0x99b
     962:	00 5f 4a             	add    %bl,0x4a(%rdi)
     965:	49 54                	rex.WB push %r12
     967:	5f                   	pop    %rdi
     968:	45                   	rex.RB
     969:	4e 54                	rex.WRX push %rsp
     96b:	52                   	push   %rdx
     96c:	59                   	pop    %rcx
     96d:	00 46 61             	add    %al,0x61(%rsi)
     970:	74 61                	je     0x9d3
     972:	6c                   	insb   (%dx),%es:(%rdi)
     973:	20 65 72             	and    %ah,0x72(%rbp)
     976:	72 6f                	jb     0x9e7
     978:	72 20                	jb     0x99a
     97a:	75 6f                	jne    0x9eb
     97c:	70 20                	jo     0x99e
     97e:	65 78 65             	gs js  0x9e6
     981:	63 75 74             	movsxd 0x74(%rbp),%esi
     984:	65 64 2e 00 00       	gs fs add %al,%fs:(%rax)
     989:	00 00                	add    %al,(%rax)
     98b:	e0 20                	loopne 0x9ad
     98d:	31 bf 69 55 00 00    	xor    %edi,0x5569(%rdi)
     993:	e0 0b                	loopne 0x9a0
     995:	46 bf 69 55 00 00    	rex.RX mov $0x5569,%edi
     99b:	50                   	push   %rax
     99c:	f0 4d bf 69 55 00 00 	lock rex.WRB movabs $0xbf2e2bd000005569,%r15
     9a3:	d0 2b 2e bf
     9a7:	69 55 00 00 f0 f2 4b 	imul   $0x4bf2f000,0x0(%rbp),%edx
     9ae:	bf 69 55 00 00       	mov    $0x5569,%edi
     9b3:	60                   	(bad)
     9b4:	8b 2e                	mov    (%rsi),%ebp
     9b6:	bf 69 55 00 00       	mov    $0x5569,%edi
     9bb:	50                   	push   %rax
     9bc:	a1 22 bf 69 55 00 00 	movabs 0x85f000005569bf22,%eax
     9c3:	f0 85
     9c5:	2e bf 69 55 00 00    	cs mov $0x5569,%edi
	...
