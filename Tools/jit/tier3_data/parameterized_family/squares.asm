
Tools/jit/tier3_data/parameterized_family/squares.bin:     file format binary


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
      30:	ff 15 ca 0a 00 00    	call   *0xaca(%rip)        # 0xb00
      36:	48 89 df             	mov    %rbx,%rdi
      39:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
      3e:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
      43:	48 83 c4 18          	add    $0x18,%rsp
      47:	e9 54 07 00 00       	jmp    0x7a0
      4c:	41 c6 44 24 24 00    	movb   $0x0,0x24(%r12)
      52:	48 b8 bc fb 41 20 7b 	movabs $0x7f7b2041fbbc,%rax
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
      83:	ff 15 57 0a 00 00    	call   *0xa57(%rip)        # 0xae0
      89:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
      8e:	4c 89 e2             	mov    %r12,%rdx
      91:	4c 8b 64 24 08       	mov    0x8(%rsp),%r12
      96:	85 c0                	test   %eax,%eax
      98:	48 8d 64 24 18       	lea    0x18(%rsp),%rsp
      9d:	74 08                	je     0xa7
      9f:	48 89 de             	mov    %rbx,%rsi
      a2:	e9 3c 07 00 00       	jmp    0x7e3
      a7:	31 ff                	xor    %edi,%edi
      a9:	31 f6                	xor    %esi,%esi
      ab:	31 d2                	xor    %edx,%edx
      ad:	41 80 7c 24 22 00    	cmpb   $0x0,0x22(%r12)
      b3:	0f 84 5e 07 00 00    	je     0x817
      b9:	49 8b 46 f0          	mov    -0x10(%r14),%rax
      bd:	48 89 c1             	mov    %rax,%rcx
      c0:	48 83 e1 fe          	and    $0xfffffffffffffffe,%rcx
      c4:	49 b8 20 cc f6 91 fd 	movabs $0x55fd91f6cc20,%r8
      cb:	55 00 00
      ce:	4c 39 41 08          	cmp    %r8,0x8(%rcx)
      d2:	0f 85 82 07 00 00    	jne    0x85a
      d8:	49 8b 76 f8          	mov    -0x8(%r14),%rsi
      dc:	49 83 c6 f0          	add    $0xfffffffffffffff0,%r14
      e0:	48 89 c7             	mov    %rax,%rdi
      e3:	48 89 f8             	mov    %rdi,%rax
      e6:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
      ea:	48 83 78 20 00       	cmpq   $0x0,0x20(%rax)
      ef:	0f 8e 8a 07 00 00    	jle    0x87f
      f5:	48 83 ec 78          	sub    $0x78,%rsp
      f9:	49 89 f8             	mov    %rdi,%r8
      fc:	48 b8 23 00 00 00 00 	movabs $0x23,%rax
     103:	00 00 00
     106:	0f b7 c8             	movzwl %ax,%ecx
     109:	c1 e9 04             	shr    $0x4,%ecx
     10c:	48 89 fb             	mov    %rdi,%rbx
     10f:	48 83 e3 fe          	and    $0xfffffffffffffffe,%rbx
     113:	49 8b 7c cd 50       	mov    0x50(%r13,%rcx,8),%rdi
     118:	c7 44 24 64 00 00 00 	movl   $0x0,0x64(%rsp)
     11f:	00
     120:	48 b8 20 cc f6 91 fd 	movabs $0x55fd91f6cc20,%rax
     127:	55 00 00
     12a:	48 39 43 08          	cmp    %rax,0x8(%rbx)
     12e:	0f 85 db 03 00 00    	jne    0x50f
     134:	48 83 e7 fe          	and    $0xfffffffffffffffe,%rdi
     138:	48 b8 00 5c f6 91 fd 	movabs $0x55fd91f65c00,%rax
     13f:	55 00 00
     142:	48 39 47 08          	cmp    %rax,0x8(%rdi)
     146:	0f 85 c3 03 00 00    	jne    0x50f
     14c:	48 89 4c 24 70       	mov    %rcx,0x70(%rsp)
     151:	4c 89 64 24 28       	mov    %r12,0x28(%rsp)
     156:	48 89 54 24 50       	mov    %rdx,0x50(%rsp)
     15b:	4c 89 7c 24 18       	mov    %r15,0x18(%rsp)
     160:	4c 89 44 24 20       	mov    %r8,0x20(%rsp)
     165:	4d 89 06             	mov    %r8,(%r14)
     168:	48 89 74 24 58       	mov    %rsi,0x58(%rsp)
     16d:	49 89 76 08          	mov    %rsi,0x8(%r14)
     171:	4c 89 74 24 30       	mov    %r14,0x30(%rsp)
     176:	49 83 c6 10          	add    $0x10,%r14
     17a:	4c 89 6c 24 10       	mov    %r13,0x10(%rsp)
     17f:	4d 89 75 40          	mov    %r14,0x40(%r13)
     183:	48 8d 74 24 64       	lea    0x64(%rsp),%rsi
     188:	ff 15 7a 09 00 00    	call   *0x97a(%rip)        # 0xb08
     18e:	49 89 c7             	mov    %rax,%r15
     191:	48 83 f8 ff          	cmp    $0xffffffffffffffff,%rax
     195:	0f 84 a4 00 00 00    	je     0x23f
     19b:	4d 89 fa             	mov    %r15,%r10
     19e:	4c 89 74 24 68       	mov    %r14,0x68(%rsp)
     1a3:	83 7c 24 64 00       	cmpl   $0x0,0x64(%rsp)
     1a8:	48 8b 74 24 58       	mov    0x58(%rsp),%rsi
     1ad:	4c 8b 44 24 20       	mov    0x20(%rsp),%r8
     1b2:	4c 8b 7c 24 18       	mov    0x18(%rsp),%r15
     1b7:	4c 8b 64 24 28       	mov    0x28(%rsp),%r12
     1bc:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     1c1:	4c 8b 74 24 30       	mov    0x30(%rsp),%r14
     1c6:	0f 85 43 03 00 00    	jne    0x50f
     1cc:	48 8b 53 20          	mov    0x20(%rbx),%rdx
     1d0:	48 83 fa 02          	cmp    $0x2,%rdx
     1d4:	0f 8c 35 03 00 00    	jl     0x50f
     1da:	49 8b 45 00          	mov    0x0(%r13),%rax
     1de:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     1e2:	4c 8b 98 a8 00 00 00 	mov    0xa8(%rax),%r11
     1e9:	48 8b 43 10          	mov    0x10(%rbx),%rax
     1ed:	48 89 44 24 38       	mov    %rax,0x38(%rsp)
     1f2:	41 8a 7c 24 22       	mov    0x22(%r12),%dil
     1f7:	40 84 ff             	test   %dil,%dil
     1fa:	0f 94 c1             	sete   %cl
     1fd:	49 8b 47 18          	mov    0x18(%r15),%rax
     201:	4c 39 d8             	cmp    %r11,%rax
     204:	0f 95 c0             	setne  %al
     207:	41 89 c1             	mov    %eax,%r9d
     20a:	89 4c 24 0c          	mov    %ecx,0xc(%rsp)
     20e:	08 c8                	or     %cl,%al
     210:	a8 01                	test   $0x1,%al
     212:	74 61                	je     0x275
     214:	b8 01 00 00 00       	mov    $0x1,%eax
     219:	48 c7 44 24 40 00 00 	movq   $0x0,0x40(%rsp)
     220:	00 00
     222:	48 c7 44 24 48 00 00 	movq   $0x0,0x48(%rsp)
     229:	00 00
     22b:	c7 44 24 08 00 00 00 	movl   $0x0,0x8(%rsp)
     232:	00
     233:	44 89 ca             	mov    %r9d,%edx
     236:	8b 7c 24 0c          	mov    0xc(%rsp),%edi
     23a:	e9 1d 01 00 00       	jmp    0x35c
     23f:	ff 15 cb 08 00 00    	call   *0x8cb(%rip)        # 0xb10
     245:	48 85 c0             	test   %rax,%rax
     248:	0f 84 4d ff ff ff    	je     0x19b
     24e:	4c 8b 64 24 28       	mov    0x28(%rsp),%r12
     253:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     258:	4c 8b 7c 24 18       	mov    0x18(%rsp),%r15
     25d:	48 8b 7c 24 20       	mov    0x20(%rsp),%rdi
     262:	48 8b 74 24 58       	mov    0x58(%rsp),%rsi
     267:	48 8b 54 24 50       	mov    0x50(%rsp),%rdx
     26c:	48 83 c4 78          	add    $0x78,%rsp
     270:	e9 8a 06 00 00       	jmp    0x8ff
     275:	4c 8d 42 ff          	lea    -0x1(%rdx),%r8
     279:	48 83 c2 fe          	add    $0xfffffffffffffffe,%rdx
     27d:	b8 01 00 00 00       	mov    $0x1,%eax
     282:	45 31 f6             	xor    %r14d,%r14d
     285:	45 31 c9             	xor    %r9d,%r9d
     288:	4c 8b 64 24 38       	mov    0x38(%rsp),%r12
     28d:	4d 89 e7             	mov    %r12,%r15
     290:	4d 89 e5             	mov    %r12,%r13
     293:	4d 0f af ec          	imul   %r12,%r13
     297:	70 75                	jo     0x30e
     299:	4d 01 d5             	add    %r10,%r13
     29c:	70 70                	jo     0x30e
     29e:	4c 8b 63 18          	mov    0x18(%rbx),%r12
     2a2:	4c 89 7c 24 48       	mov    %r15,0x48(%rsp)
     2a7:	4d 01 fc             	add    %r15,%r12
     2aa:	4c 39 f2             	cmp    %r14,%rdx
     2ad:	74 78                	je     0x327
     2af:	4c 8b 4c 24 18       	mov    0x18(%rsp),%r9
     2b4:	4d 8b 49 18          	mov    0x18(%r9),%r9
     2b8:	49 ff c6             	inc    %r14
     2bb:	4d 39 d9             	cmp    %r11,%r9
     2be:	41 0f 95 c7          	setne  %r15b
     2c2:	75 10                	jne    0x2d4
     2c4:	48 ff c0             	inc    %rax
     2c7:	4c 8b 4c 24 48       	mov    0x48(%rsp),%r9
     2cc:	4d 89 ea             	mov    %r13,%r10
     2cf:	40 84 ff             	test   %dil,%dil
     2d2:	75 b9                	jne    0x28d
     2d4:	4d 89 ea             	mov    %r13,%r10
     2d7:	4c 89 64 24 38       	mov    %r12,0x38(%rsp)
     2dc:	4c 89 74 24 40       	mov    %r14,0x40(%rsp)
     2e1:	49 8d 46 01          	lea    0x1(%r14),%rax
     2e5:	c7 44 24 08 00 00 00 	movl   $0x0,0x8(%rsp)
     2ec:	00
     2ed:	4c 8b 44 24 20       	mov    0x20(%rsp),%r8
     2f2:	44 89 fa             	mov    %r15d,%edx
     2f5:	4c 8b 7c 24 18       	mov    0x18(%rsp),%r15
     2fa:	4c 8b 64 24 28       	mov    0x28(%rsp),%r12
     2ff:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     304:	4c 8b 74 24 30       	mov    0x30(%rsp),%r14
     309:	e9 28 ff ff ff       	jmp    0x236
     30e:	b2 01                	mov    $0x1,%dl
     310:	89 54 24 08          	mov    %edx,0x8(%rsp)
     314:	4c 89 74 24 40       	mov    %r14,0x40(%rsp)
     319:	31 d2                	xor    %edx,%edx
     31b:	4c 89 7c 24 38       	mov    %r15,0x38(%rsp)
     320:	4c 89 4c 24 48       	mov    %r9,0x48(%rsp)
     325:	eb 1a                	jmp    0x341
     327:	4d 89 ea             	mov    %r13,%r10
     32a:	4c 89 64 24 38       	mov    %r12,0x38(%rsp)
     32f:	c7 44 24 08 00 00 00 	movl   $0x0,0x8(%rsp)
     336:	00
     337:	4c 89 c0             	mov    %r8,%rax
     33a:	4c 89 44 24 40       	mov    %r8,0x40(%rsp)
     33f:	31 d2                	xor    %edx,%edx
     341:	31 ff                	xor    %edi,%edi
     343:	4c 8b 44 24 20       	mov    0x20(%rsp),%r8
     348:	4c 8b 7c 24 18       	mov    0x18(%rsp),%r15
     34d:	4c 8b 64 24 28       	mov    0x28(%rsp),%r12
     352:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     357:	4c 8b 74 24 30       	mov    0x30(%rsp),%r14
     35c:	40 08 fa             	or     %dil,%dl
     35f:	49 01 84 24 c0 00 00 	add    %rax,0xc0(%r12)
     366:	00
     367:	89 54 24 0c          	mov    %edx,0xc(%rsp)
     36b:	f6 c2 01             	test   $0x1,%dl
     36e:	74 08                	je     0x378
     370:	49 ff 84 24 c8 00 00 	incq   0xc8(%r12)
     377:	00
     378:	48 83 7c 24 40 00    	cmpq   $0x0,0x40(%rsp)
     37e:	0f 84 15 01 00 00    	je     0x499
     384:	4d 89 06             	mov    %r8,(%r14)
     387:	49 89 76 08          	mov    %rsi,0x8(%r14)
     38b:	4c 8b 74 24 68       	mov    0x68(%rsp),%r14
     390:	4d 89 75 40          	mov    %r14,0x40(%r13)
     394:	4c 89 d7             	mov    %r10,%rdi
     397:	ff 15 7b 07 00 00    	call   *0x77b(%rip)        # 0xb18
     39d:	48 85 c0             	test   %rax,%rax
     3a0:	0f 84 a8 fe ff ff    	je     0x24e
     3a6:	49 89 c4             	mov    %rax,%r12
     3a9:	48 8b 7c 24 48       	mov    0x48(%rsp),%rdi
     3ae:	ff 15 3c 07 00 00    	call   *0x73c(%rip)        # 0xaf0
     3b4:	48 85 c0             	test   %rax,%rax
     3b7:	0f 84 03 01 00 00    	je     0x4c0
     3bd:	48 b9 23 00 00 00 00 	movabs $0x23,%rcx
     3c4:	00 00 00
     3c7:	83 e1 0f             	and    $0xf,%ecx
     3ca:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     3cf:	48 8b 74 24 70       	mov    0x70(%rsp),%rsi
     3d4:	49 8b 7c f5 50       	mov    0x50(%r13,%rsi,8),%rdi
     3d9:	89 c9                	mov    %ecx,%ecx
     3db:	4d 8b 44 cd 50       	mov    0x50(%r13,%rcx,8),%r8
     3e0:	41 0f b7 54 24 06    	movzwl 0x6(%r12),%edx
     3e6:	83 e2 01             	and    $0x1,%edx
     3e9:	4c 09 e2             	or     %r12,%rdx
     3ec:	49 89 54 f5 50       	mov    %rdx,0x50(%r13,%rsi,8)
     3f1:	0f b7 50 06          	movzwl 0x6(%rax),%edx
     3f5:	83 e2 01             	and    $0x1,%edx
     3f8:	48 09 c2             	or     %rax,%rdx
     3fb:	49 89 54 cd 50       	mov    %rdx,0x50(%r13,%rcx,8)
     400:	48 8b 44 24 38       	mov    0x38(%rsp),%rax
     405:	48 89 43 10          	mov    %rax,0x10(%rbx)
     409:	4c 8b 74 24 40       	mov    0x40(%rsp),%r14
     40e:	4c 29 73 20          	sub    %r14,0x20(%rbx)
     412:	40 f6 c7 01          	test   $0x1,%dil
     416:	75 15                	jne    0x42d
     418:	ff 0f                	decl   (%rdi)
     41a:	75 11                	jne    0x42d
     41c:	4c 89 c3             	mov    %r8,%rbx
     41f:	ff 15 ab 06 00 00    	call   *0x6ab(%rip)        # 0xad0
     425:	49 89 d8             	mov    %rbx,%r8
     428:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     42d:	41 f6 c0 01          	test   $0x1,%r8b
     431:	8b 5c 24 0c          	mov    0xc(%rsp),%ebx
     435:	44 8b 7c 24 08       	mov    0x8(%rsp),%r15d
     43a:	75 13                	jne    0x44f
     43c:	41 ff 08             	decl   (%r8)
     43f:	75 0e                	jne    0x44f
     441:	4c 89 c7             	mov    %r8,%rdi
     444:	ff 15 86 06 00 00    	call   *0x686(%rip)        # 0xad0
     44a:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     44f:	4c 8b 64 24 28       	mov    0x28(%rsp),%r12
     454:	49 ff 84 24 b0 00 00 	incq   0xb0(%r12)
     45b:	00
     45c:	4d 01 b4 24 b8 00 00 	add    %r14,0xb8(%r12)
     463:	00
     464:	f6 c3 01             	test   $0x1,%bl
     467:	74 7d                	je     0x4e6
     469:	49 ff 84 24 e0 00 00 	incq   0xe0(%r12)
     470:	00
     471:	45 84 ff             	test   %r15b,%r15b
     474:	48 8b 74 24 58       	mov    0x58(%rsp),%rsi
     479:	4c 8b 44 24 20       	mov    0x20(%rsp),%r8
     47e:	4c 8b 7c 24 18       	mov    0x18(%rsp),%r15
     483:	48 8b 54 24 50       	mov    0x50(%rsp),%rdx
     488:	4c 8b 74 24 30       	mov    0x30(%rsp),%r14
     48d:	74 25                	je     0x4b4
     48f:	49 ff 84 24 d0 00 00 	incq   0xd0(%r12)
     496:	00
     497:	eb 1b                	jmp    0x4b4
     499:	80 7c 24 08 00       	cmpb   $0x0,0x8(%rsp)
     49e:	74 08                	je     0x4a8
     4a0:	49 ff 84 24 d0 00 00 	incq   0xd0(%r12)
     4a7:	00
     4a8:	f6 44 24 0c 01       	testb  $0x1,0xc(%rsp)
     4ad:	48 8b 54 24 50       	mov    0x50(%rsp),%rdx
     4b2:	74 5b                	je     0x50f
     4b4:	4c 89 c7             	mov    %r8,%rdi
     4b7:	48 83 c4 78          	add    $0x78,%rsp
     4bb:	e9 ef 03 00 00       	jmp    0x8af
     4c0:	41 8b 04 24          	mov    (%r12),%eax
     4c4:	85 c0                	test   %eax,%eax
     4c6:	0f 88 82 fd ff ff    	js     0x24e
     4cc:	ff c8                	dec    %eax
     4ce:	41 89 04 24          	mov    %eax,(%r12)
     4d2:	0f 85 76 fd ff ff    	jne    0x24e
     4d8:	4c 89 e7             	mov    %r12,%rdi
     4db:	ff 15 ef 05 00 00    	call   *0x5ef(%rip)        # 0xad0
     4e1:	e9 68 fd ff ff       	jmp    0x24e
     4e6:	49 ff 84 24 d8 00 00 	incq   0xd8(%r12)
     4ed:	00
     4ee:	45 84 ff             	test   %r15b,%r15b
     4f1:	48 8b 74 24 58       	mov    0x58(%rsp),%rsi
     4f6:	4c 8b 44 24 20       	mov    0x20(%rsp),%r8
     4fb:	4c 8b 7c 24 18       	mov    0x18(%rsp),%r15
     500:	4c 8b 74 24 30       	mov    0x30(%rsp),%r14
     505:	74 08                	je     0x50f
     507:	49 ff 84 24 d0 00 00 	incq   0xd0(%r12)
     50e:	00
     50f:	4c 89 c7             	mov    %r8,%rdi
     512:	31 d2                	xor    %edx,%edx
     514:	48 83 c4 78          	add    $0x78,%rsp
     518:	48 83 ec 18          	sub    $0x18,%rsp
     51c:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
     521:	48 89 74 24 08       	mov    %rsi,0x8(%rsp)
     526:	48 89 fb             	mov    %rdi,%rbx
     529:	48 89 f8             	mov    %rdi,%rax
     52c:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     530:	48 8b 78 10          	mov    0x10(%rax),%rdi
     534:	48 8b 48 18          	mov    0x18(%rax),%rcx
     538:	48 01 f9             	add    %rdi,%rcx
     53b:	48 89 48 10          	mov    %rcx,0x10(%rax)
     53f:	48 ff 48 20          	decq   0x20(%rax)
     543:	ff 15 a7 05 00 00    	call   *0x5a7(%rip)        # 0xaf0
     549:	48 85 c0             	test   %rax,%rax
     54c:	74 18                	je     0x566
     54e:	0f b7 50 06          	movzwl 0x6(%rax),%edx
     552:	83 e2 01             	and    $0x1,%edx
     555:	48 09 c2             	or     %rax,%rdx
     558:	48 89 df             	mov    %rbx,%rdi
     55b:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     560:	48 83 c4 18          	add    $0x18,%rsp
     564:	eb 21                	jmp    0x587
     566:	49 89 1e             	mov    %rbx,(%r14)
     569:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     56e:	49 89 76 08          	mov    %rsi,0x8(%r14)
     572:	49 83 c6 10          	add    $0x10,%r14
     576:	48 89 df             	mov    %rbx,%rdi
     579:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
     57e:	48 83 c4 18          	add    $0x18,%rsp
     582:	e9 ac 03 00 00       	jmp    0x933
     587:	48 b8 9c fb 41 20 7b 	movabs $0x7f7b2041fb9c,%rax
     58e:	7f 00 00
     591:	49 89 45 38          	mov    %rax,0x38(%r13)
     595:	49 8b 45 68          	mov    0x68(%r13),%rax
     599:	49 89 55 68          	mov    %rdx,0x68(%r13)
     59d:	48 89 c2             	mov    %rax,%rdx
     5a0:	49 89 3e             	mov    %rdi,(%r14)
     5a3:	49 89 76 08          	mov    %rsi,0x8(%r14)
     5a7:	49 83 c6 10          	add    $0x10,%r14
     5ab:	48 89 d7             	mov    %rdx,%rdi
     5ae:	4d 89 75 40          	mov    %r14,0x40(%r13)
     5b2:	40 f6 c7 01          	test   $0x1,%dil
     5b6:	75 0f                	jne    0x5c7
     5b8:	ff 0f                	decl   (%rdi)
     5ba:	75 0b                	jne    0x5c7
     5bc:	50                   	push   %rax
     5bd:	ff 15 0d 05 00 00    	call   *0x50d(%rip)        # 0xad0
     5c3:	48 83 c4 08          	add    $0x8,%rsp
     5c7:	31 ff                	xor    %edi,%edi
     5c9:	31 f6                	xor    %esi,%esi
     5cb:	31 d2                	xor    %edx,%edx
     5cd:	41 80 7c 24 22 00    	cmpb   $0x0,0x22(%r12)
     5d3:	0f 84 8e 03 00 00    	je     0x967
     5d9:	49 8b 7d 60          	mov    0x60(%r13),%rdi
     5dd:	48 83 cf 01          	or     $0x1,%rdi
     5e1:	49 8b 75 68          	mov    0x68(%r13),%rsi
     5e5:	48 83 ce 01          	or     $0x1,%rsi
     5e9:	49 8b 55 68          	mov    0x68(%r13),%rdx
     5ed:	48 83 ca 01          	or     $0x1,%rdx
     5f1:	48 89 d0             	mov    %rdx,%rax
     5f4:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     5f8:	48 83 78 10 10       	cmpq   $0x10,0x10(%rax)
     5fd:	0f 83 a7 03 00 00    	jae    0x9aa
     603:	49 89 3e             	mov    %rdi,(%r14)
     606:	49 83 c6 08          	add    $0x8,%r14
     60a:	48 89 f7             	mov    %rsi,%rdi
     60d:	48 89 d6             	mov    %rdx,%rsi
     610:	48 83 ec 18          	sub    $0x18,%rsp
     614:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
     619:	48 89 fb             	mov    %rdi,%rbx
     61c:	48 83 e7 fe          	and    $0xfffffffffffffffe,%rdi
     620:	48 89 74 24 08       	mov    %rsi,0x8(%rsp)
     625:	48 83 e6 fe          	and    $0xfffffffffffffffe,%rsi
     629:	ff 15 a9 04 00 00    	call   *0x4a9(%rip)        # 0xad8
     62f:	48 83 f8 01          	cmp    $0x1,%rax
     633:	75 16                	jne    0x64b
     635:	48 89 df             	mov    %rbx,%rdi
     638:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     63d:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
     642:	48 83 c4 18          	add    $0x18,%rsp
     646:	e9 93 03 00 00       	jmp    0x9de
     64b:	48 89 c7             	mov    %rax,%rdi
     64e:	48 89 de             	mov    %rbx,%rsi
     651:	48 8b 54 24 08       	mov    0x8(%rsp),%rdx
     656:	48 83 c4 18          	add    $0x18,%rsp
     65a:	48 b8 ae fb 41 20 7b 	movabs $0x7f7b2041fbae,%rax
     661:	7f 00 00
     664:	49 89 45 38          	mov    %rax,0x38(%r13)
     668:	48 89 fe             	mov    %rdi,%rsi
     66b:	49 8b 7e f8          	mov    -0x8(%r14),%rdi
     66f:	49 83 c6 f8          	add    $0xfffffffffffffff8,%r14
     673:	48 83 ec 18          	sub    $0x18,%rsp
     677:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
     67c:	48 89 f0             	mov    %rsi,%rax
     67f:	48 89 fb             	mov    %rdi,%rbx
     682:	4c 89 3c 24          	mov    %r15,(%rsp)
     686:	48 83 e7 fe          	and    $0xfffffffffffffffe,%rdi
     68a:	48 83 e6 fe          	and    $0xfffffffffffffffe,%rsi
     68e:	49 89 1e             	mov    %rbx,(%r14)
     691:	48 89 44 24 08       	mov    %rax,0x8(%rsp)
     696:	49 89 46 08          	mov    %rax,0x8(%r14)
     69a:	4d 8d 7e 10          	lea    0x10(%r14),%r15
     69e:	4d 89 7d 40          	mov    %r15,0x40(%r13)
     6a2:	48 b8 0d 00 00 00 00 	movabs $0xd,%rax
     6a9:	00 00 00
     6ac:	0f b7 c0             	movzwl %ax,%eax
     6af:	48 b9 a0 35 f1 91 fd 	movabs $0x55fd91f135a0,%rcx
     6b6:	55 00 00
     6b9:	ff 14 c1             	call   *(%rcx,%rax,8)
     6bc:	48 85 c0             	test   %rax,%rax
     6bf:	74 1c                	je     0x6dd
     6c1:	0f b7 78 06          	movzwl 0x6(%rax),%edi
     6c5:	83 e7 01             	and    $0x1,%edi
     6c8:	48 09 c7             	or     %rax,%rdi
     6cb:	4c 8b 3c 24          	mov    (%rsp),%r15
     6cf:	48 89 de             	mov    %rbx,%rsi
     6d2:	48 8b 54 24 08       	mov    0x8(%rsp),%rdx
     6d7:	48 83 c4 18          	add    $0x18,%rsp
     6db:	eb 1d                	jmp    0x6fa
     6dd:	4d 89 fe             	mov    %r15,%r14
     6e0:	4c 8b 3c 24          	mov    (%rsp),%r15
     6e4:	48 89 df             	mov    %rbx,%rdi
     6e7:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     6ec:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
     6f1:	48 83 c4 18          	add    $0x18,%rsp
     6f5:	e9 14 03 00 00       	jmp    0xa0e
     6fa:	48 89 d3             	mov    %rdx,%rbx
     6fd:	f6 c3 01             	test   $0x1,%bl
     700:	75 52                	jne    0x754
     702:	ff 0b                	decl   (%rbx)
     704:	75 4e                	jne    0x754
     706:	48 83 ec 18          	sub    $0x18,%rsp
     70a:	48 89 7c 24 08       	mov    %rdi,0x8(%rsp)
     70f:	48 89 74 24 10       	mov    %rsi,0x10(%rsp)
     714:	48 b8 30 c2 f9 91 fd 	movabs $0x55fd91f9c230,%rax
     71b:	55 00 00
     71e:	48 8b 00             	mov    (%rax),%rax
     721:	48 85 c0             	test   %rax,%rax
     724:	74 17                	je     0x73d
     726:	48 b9 38 c2 f9 91 fd 	movabs $0x55fd91f9c238,%rcx
     72d:	55 00 00
     730:	48 8b 11             	mov    (%rcx),%rdx
     733:	48 89 df             	mov    %rbx,%rdi
     736:	be 01 00 00 00       	mov    $0x1,%esi
     73b:	ff d0                	call   *%rax
     73d:	48 89 df             	mov    %rbx,%rdi
     740:	ff 15 b2 03 00 00    	call   *0x3b2(%rip)        # 0xaf8
     746:	48 8b 74 24 10       	mov    0x10(%rsp),%rsi
     74b:	48 8b 7c 24 08       	mov    0x8(%rsp),%rdi
     750:	48 83 c4 18          	add    $0x18,%rsp
     754:	48 89 da             	mov    %rbx,%rdx
     757:	41 80 7c 24 22 00    	cmpb   $0x0,0x22(%r12)
     75d:	0f 84 df 02 00 00    	je     0xa42
     763:	48 b8 ba fb 41 20 7b 	movabs $0x7f7b2041fbba,%rax
     76a:	7f 00 00
     76d:	49 89 45 38          	mov    %rax,0x38(%r13)
     771:	49 8b 45 60          	mov    0x60(%r13),%rax
     775:	49 89 7d 60          	mov    %rdi,0x60(%r13)
     779:	48 89 c7             	mov    %rax,%rdi
     77c:	4d 89 75 40          	mov    %r14,0x40(%r13)
     780:	40 f6 c7 01          	test   $0x1,%dil
     784:	75 0f                	jne    0x795
     786:	ff 0f                	decl   (%rdi)
     788:	75 0b                	jne    0x795
     78a:	50                   	push   %rax
     78b:	ff 15 3f 03 00 00    	call   *0x33f(%rip)        # 0xad0
     791:	48 83 c4 08          	add    $0x8,%rsp
     795:	31 ff                	xor    %edi,%edi
     797:	31 f6                	xor    %esi,%esi
     799:	31 d2                	xor    %edx,%edx
     79b:	e9 ac f8 ff ff       	jmp    0x4c
     7a0:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     7a7:	00 00 00 00
     7ab:	4d 89 75 40          	mov    %r14,0x40(%r13)
     7af:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     7b4:	75 0e                	jne    0x7c4
     7b6:	48 b8 c0 89 f7 91 fd 	movabs $0x55fd91f789c0,%rax
     7bd:	55 00 00
     7c0:	48 8b 00             	mov    (%rax),%rax
     7c3:	c3                   	ret
     7c4:	49 8b 45 00          	mov    0x0(%r13),%rax
     7c8:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     7cc:	48 b9 22 00 00 00 00 	movabs $0x22,%rcx
     7d3:	00 00 00
     7d6:	89 c9                	mov    %ecx,%ecx
     7d8:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     7dc:	48 05 c8 00 00 00    	add    $0xc8,%rax
     7e2:	c3                   	ret
     7e3:	49 8b 45 00          	mov    0x0(%r13),%rax
     7e7:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     7eb:	48 b9 22 00 00 00 00 	movabs $0x22,%rcx
     7f2:	00 00 00
     7f5:	89 c9                	mov    %ecx,%ecx
     7f7:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     7fb:	48 05 c8 00 00 00    	add    $0xc8,%rax
     801:	49 89 45 38          	mov    %rax,0x38(%r13)
     805:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     80c:	00 00 00 00
     810:	4d 89 75 40          	mov    %r14,0x40(%r13)
     814:	31 c0                	xor    %eax,%eax
     816:	c3                   	ret
     817:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     81e:	00 00 00 00
     822:	4d 89 75 40          	mov    %r14,0x40(%r13)
     826:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     82b:	75 0e                	jne    0x83b
     82d:	48 b8 c0 89 f7 91 fd 	movabs $0x55fd91f789c0,%rax
     834:	55 00 00
     837:	48 8b 00             	mov    (%rax),%rax
     83a:	c3                   	ret
     83b:	49 8b 45 00          	mov    0x0(%r13),%rax
     83f:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     843:	48 b9 10 00 00 00 00 	movabs $0x10,%rcx
     84a:	00 00 00
     84d:	89 c9                	mov    %ecx,%ecx
     84f:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     853:	48 05 c8 00 00 00    	add    $0xc8,%rax
     859:	c3                   	ret
     85a:	48 b8 38 02 c4 b3 fd 	movabs $0x55fdb3c40238,%rax
     861:	55 00 00
     864:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     86b:	48 b8 40 02 c4 b3 fd 	movabs $0x55fdb3c40240,%rax
     872:	55 00 00
     875:	4c 8b 20             	mov    (%rax),%r12
     878:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     87d:	ff e0                	jmp    *%rax
     87f:	48 b8 48 02 c4 b3 fd 	movabs $0x55fdb3c40248,%rax
     886:	55 00 00
     889:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     890:	49 89 3e             	mov    %rdi,(%r14)
     893:	49 89 76 08          	mov    %rsi,0x8(%r14)
     897:	49 83 c6 10          	add    $0x10,%r14
     89b:	48 b8 50 02 c4 b3 fd 	movabs $0x55fdb3c40250,%rax
     8a2:	55 00 00
     8a5:	4c 8b 20             	mov    (%rax),%r12
     8a8:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     8ad:	ff e0                	jmp    *%rax
     8af:	50                   	push   %rax
     8b0:	49 89 3e             	mov    %rdi,(%r14)
     8b3:	49 89 76 08          	mov    %rsi,0x8(%r14)
     8b7:	49 83 c6 10          	add    $0x10,%r14
     8bb:	4d 89 75 40          	mov    %r14,0x40(%r13)
     8bf:	4c 89 ff             	mov    %r15,%rdi
     8c2:	ff 15 18 02 00 00    	call   *0x218(%rip)        # 0xae0
     8c8:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     8cf:	00 00 00 00
     8d3:	4d 89 75 40          	mov    %r14,0x40(%r13)
     8d7:	85 c0                	test   %eax,%eax
     8d9:	74 04                	je     0x8df
     8db:	31 c0                	xor    %eax,%eax
     8dd:	eb 1e                	jmp    0x8fd
     8df:	49 8b 45 00          	mov    0x0(%r13),%rax
     8e3:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     8e7:	48 b9 22 00 00 00 00 	movabs $0x22,%rcx
     8ee:	00 00 00
     8f1:	89 c9                	mov    %ecx,%ecx
     8f3:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     8f7:	48 05 c8 00 00 00    	add    $0xc8,%rax
     8fd:	59                   	pop    %rcx
     8fe:	c3                   	ret
     8ff:	49 8b 45 00          	mov    0x0(%r13),%rax
     903:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     907:	48 b9 1b 00 00 00 00 	movabs $0x1b,%rcx
     90e:	00 00 00
     911:	89 c9                	mov    %ecx,%ecx
     913:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     917:	48 05 c8 00 00 00    	add    $0xc8,%rax
     91d:	49 89 45 38          	mov    %rax,0x38(%r13)
     921:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     928:	00 00 00 00
     92c:	4d 89 75 40          	mov    %r14,0x40(%r13)
     930:	31 c0                	xor    %eax,%eax
     932:	c3                   	ret
     933:	49 8b 45 00          	mov    0x0(%r13),%rax
     937:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     93b:	48 b9 10 00 00 00 00 	movabs $0x10,%rcx
     942:	00 00 00
     945:	89 c9                	mov    %ecx,%ecx
     947:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     94b:	48 05 c8 00 00 00    	add    $0xc8,%rax
     951:	49 89 45 38          	mov    %rax,0x38(%r13)
     955:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     95c:	00 00 00 00
     960:	4d 89 75 40          	mov    %r14,0x40(%r13)
     964:	31 c0                	xor    %eax,%eax
     966:	c3                   	ret
     967:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     96e:	00 00 00 00
     972:	4d 89 75 40          	mov    %r14,0x40(%r13)
     976:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     97b:	75 0e                	jne    0x98b
     97d:	48 b8 c0 89 f7 91 fd 	movabs $0x55fd91f789c0,%rax
     984:	55 00 00
     987:	48 8b 00             	mov    (%rax),%rax
     98a:	c3                   	ret
     98b:	49 8b 45 00          	mov    0x0(%r13),%rax
     98f:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     993:	48 b9 13 00 00 00 00 	movabs $0x13,%rcx
     99a:	00 00 00
     99d:	89 c9                	mov    %ecx,%ecx
     99f:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     9a3:	48 05 c8 00 00 00    	add    $0xc8,%rax
     9a9:	c3                   	ret
     9aa:	48 b8 58 02 c4 b3 fd 	movabs $0x55fdb3c40258,%rax
     9b1:	55 00 00
     9b4:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     9bb:	49 89 3e             	mov    %rdi,(%r14)
     9be:	49 89 76 08          	mov    %rsi,0x8(%r14)
     9c2:	49 89 56 10          	mov    %rdx,0x10(%r14)
     9c6:	49 83 c6 18          	add    $0x18,%r14
     9ca:	48 b8 60 02 c4 b3 fd 	movabs $0x55fdb3c40260,%rax
     9d1:	55 00 00
     9d4:	4c 8b 20             	mov    (%rax),%r12
     9d7:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     9dc:	ff e0                	jmp    *%rax
     9de:	48 b8 68 02 c4 b3 fd 	movabs $0x55fdb3c40268,%rax
     9e5:	55 00 00
     9e8:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     9ef:	49 89 3e             	mov    %rdi,(%r14)
     9f2:	49 89 76 08          	mov    %rsi,0x8(%r14)
     9f6:	49 83 c6 10          	add    $0x10,%r14
     9fa:	48 b8 70 02 c4 b3 fd 	movabs $0x55fdb3c40270,%rax
     a01:	55 00 00
     a04:	4c 8b 20             	mov    (%rax),%r12
     a07:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     a0c:	ff e0                	jmp    *%rax
     a0e:	49 8b 45 00          	mov    0x0(%r13),%rax
     a12:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     a16:	48 b9 1b 00 00 00 00 	movabs $0x1b,%rcx
     a1d:	00 00 00
     a20:	89 c9                	mov    %ecx,%ecx
     a22:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     a26:	48 05 c8 00 00 00    	add    $0xc8,%rax
     a2c:	49 89 45 38          	mov    %rax,0x38(%r13)
     a30:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     a37:	00 00 00 00
     a3b:	4d 89 75 40          	mov    %r14,0x40(%r13)
     a3f:	31 c0                	xor    %eax,%eax
     a41:	c3                   	ret
     a42:	49 89 3e             	mov    %rdi,(%r14)
     a45:	49 83 c6 08          	add    $0x8,%r14
     a49:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     a50:	00 00 00 00
     a54:	4d 89 75 40          	mov    %r14,0x40(%r13)
     a58:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     a5d:	75 0e                	jne    0xa6d
     a5f:	48 b8 c0 89 f7 91 fd 	movabs $0x55fd91f789c0,%rax
     a66:	55 00 00
     a69:	48 8b 00             	mov    (%rax),%rax
     a6c:	c3                   	ret
     a6d:	49 8b 45 00          	mov    0x0(%r13),%rax
     a71:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     a75:	48 b9 21 00 00 00 00 	movabs $0x21,%rcx
     a7c:	00 00 00
     a7f:	89 c9                	mov    %ecx,%ecx
     a81:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     a85:	48 05 c8 00 00 00    	add    $0xc8,%rax
     a8b:	c3                   	ret
     a8c:	50                   	push   %rax
     a8d:	48 bf a8 da ea 1f 7b 	movabs $0x7f7b1feadaa8,%rdi
     a94:	7f 00 00
     a97:	48 be b3 da ea 1f 7b 	movabs $0x7f7b1feadab3,%rsi
     a9e:	7f 00 00
     aa1:	ff 15 41 00 00 00    	call   *0x41(%rip)        # 0xae8
     aa7:	00 5f 4a             	add    %bl,0x4a(%rdi)
     aaa:	49 54                	rex.WB push %r12
     aac:	5f                   	pop    %rdi
     aad:	45                   	rex.RB
     aae:	4e 54                	rex.WRX push %rsp
     ab0:	52                   	push   %rdx
     ab1:	59                   	pop    %rcx
     ab2:	00 46 61             	add    %al,0x61(%rsi)
     ab5:	74 61                	je     0xb18
     ab7:	6c                   	insb   (%dx),%es:(%rdi)
     ab8:	20 65 72             	and    %ah,0x72(%rbp)
     abb:	72 6f                	jb     0xb2c
     abd:	72 20                	jb     0xadf
     abf:	75 6f                	jne    0xb30
     ac1:	70 20                	jo     0xae3
     ac3:	65 78 65             	gs js  0xb2b
     ac6:	63 75 74             	movsxd 0x74(%rbp),%esi
     ac9:	65 64 2e 00 00       	gs fs add %al,%fs:(%rax)
     ace:	00 00                	add    %al,(%rax)
     ad0:	e0 00                	loopne 0xad2
     ad2:	a9 91 fd 55 00       	test   $0x55fd91,%eax
     ad7:	00 00                	add    %al,(%rax)
     ad9:	9d                   	popf
     ada:	a6                   	cmpsb  %es:(%rdi),%ds:(%rsi)
     adb:	91                   	xchg   %eax,%ecx
     adc:	fd                   	std
     add:	55                   	push   %rbp
     ade:	00 00                	add    %al,(%rax)
     ae0:	e0 eb                	loopne 0xacd
     ae2:	bd 91 fd 55 00       	mov    $0x55fd91,%ebp
     ae7:	00 50 d0             	add    %dl,-0x30(%rax)
     aea:	c5 91 fd 55 00       	vpaddw 0x0(%rbp),%xmm13,%xmm2
     aef:	00 d0                	add    %dl,%al
     af1:	0b a6 91 fd 55 00    	or     0x55fd91(%rsi),%esp
     af7:	00 80 4a a5 91 fd    	add    %al,-0x26e5ab6(%rax)
     afd:	55                   	push   %rbp
     afe:	00 00                	add    %al,(%rax)
     b00:	f0 d2 c3             	lock rol %cl,%bl
     b03:	91                   	xchg   %eax,%ecx
     b04:	fd                   	std
     b05:	55                   	push   %rbp
     b06:	00 00                	add    %al,(%rax)
     b08:	60                   	(bad)
     b09:	6b a6 91 fd 55 00 00 	imul   $0x0,0x55fd91(%rsi),%esp
     b10:	50                   	push   %rax
     b11:	81 9a 91 fd 55 00 00 	sbbl   $0xa665f000,0x55fd91(%rdx)
     b18:	f0 65 a6
     b1b:	91                   	xchg   %eax,%ecx
     b1c:	fd                   	std
     b1d:	55                   	push   %rbp
	...
