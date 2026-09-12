
Tools/jit/tier3_data/native_followup/total.bin:     file format binary


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
      30:	ff 15 17 0a 00 00    	call   *0xa17(%rip)        # 0xa4d
      36:	48 89 df             	mov    %rbx,%rdi
      39:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
      3e:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
      43:	48 83 c4 18          	add    $0x18,%rsp
      47:	e9 4c 07 00 00       	jmp    0x798
      4c:	41 c6 44 24 24 00    	movb   $0x0,0x24(%r12)
      52:	48 b8 7e a8 4a 88 cd 	movabs $0x7fcd884aa87e,%rax
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
      83:	ff 15 a4 09 00 00    	call   *0x9a4(%rip)        # 0xa2d
      89:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
      8e:	4c 89 e2             	mov    %r12,%rdx
      91:	4c 8b 64 24 08       	mov    0x8(%rsp),%r12
      96:	85 c0                	test   %eax,%eax
      98:	48 8d 64 24 18       	lea    0x18(%rsp),%rsp
      9d:	74 08                	je     0xa7
      9f:	48 89 de             	mov    %rbx,%rsi
      a2:	e9 34 07 00 00       	jmp    0x7db
      a7:	31 ff                	xor    %edi,%edi
      a9:	31 f6                	xor    %esi,%esi
      ab:	31 d2                	xor    %edx,%edx
      ad:	41 80 7c 24 22 00    	cmpb   $0x0,0x22(%r12)
      b3:	0f 84 56 07 00 00    	je     0x80f
      b9:	49 8b 46 f0          	mov    -0x10(%r14),%rax
      bd:	48 89 c1             	mov    %rax,%rcx
      c0:	48 83 e1 fe          	and    $0xfffffffffffffffe,%rcx
      c4:	49 b8 20 fc 14 68 09 	movabs $0x56096814fc20,%r8
      cb:	56 00 00 
      ce:	4c 39 41 08          	cmp    %r8,0x8(%rcx)
      d2:	0f 85 7a 07 00 00    	jne    0x852
      d8:	49 8b 76 f8          	mov    -0x8(%r14),%rsi
      dc:	49 83 c6 f0          	add    $0xfffffffffffffff0,%r14
      e0:	48 89 c7             	mov    %rax,%rdi
      e3:	48 89 f8             	mov    %rdi,%rax
      e6:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
      ea:	48 83 78 20 00       	cmpq   $0x0,0x20(%rax)
      ef:	0f 8e 82 07 00 00    	jle    0x877
      f5:	48 83 ec 78          	sub    $0x78,%rsp
      f9:	49 89 f8             	mov    %rdi,%r8
      fc:	4d 89 f9             	mov    %r15,%r9
      ff:	48 b8 23 00 00 00 00 	movabs $0x23,%rax
     106:	00 00 00 
     109:	0f b7 d8             	movzwl %ax,%ebx
     10c:	c1 eb 04             	shr    $0x4,%ebx
     10f:	49 89 ff             	mov    %rdi,%r15
     112:	49 83 e7 fe          	and    $0xfffffffffffffffe,%r15
     116:	49 8b 7c dd 50       	mov    0x50(%r13,%rbx,8),%rdi
     11b:	c7 44 24 64 00 00 00 	movl   $0x0,0x64(%rsp)
     122:	00 
     123:	48 b8 20 fc 14 68 09 	movabs $0x56096814fc20,%rax
     12a:	56 00 00 
     12d:	49 39 47 08          	cmp    %rax,0x8(%r15)
     131:	0f 85 34 04 00 00    	jne    0x56b
     137:	49 83 7f 18 01       	cmpq   $0x1,0x18(%r15)
     13c:	0f 85 29 04 00 00    	jne    0x56b
     142:	48 83 e7 fe          	and    $0xfffffffffffffffe,%rdi
     146:	48 b8 00 8c 14 68 09 	movabs $0x560968148c00,%rax
     14d:	56 00 00 
     150:	48 39 47 08          	cmp    %rax,0x8(%rdi)
     154:	0f 85 11 04 00 00    	jne    0x56b
     15a:	4c 89 64 24 30       	mov    %r12,0x30(%rsp)
     15f:	4c 89 4c 24 28       	mov    %r9,0x28(%rsp)
     164:	48 89 54 24 50       	mov    %rdx,0x50(%rsp)
     169:	4c 89 44 24 10       	mov    %r8,0x10(%rsp)
     16e:	4d 89 06             	mov    %r8,(%r14)
     171:	48 89 74 24 18       	mov    %rsi,0x18(%rsp)
     176:	49 89 76 08          	mov    %rsi,0x8(%r14)
     17a:	4c 89 74 24 58       	mov    %r14,0x58(%rsp)
     17f:	49 83 c6 10          	add    $0x10,%r14
     183:	4c 89 6c 24 20       	mov    %r13,0x20(%rsp)
     188:	4d 89 75 40          	mov    %r14,0x40(%r13)
     18c:	48 8d 74 24 64       	lea    0x64(%rsp),%rsi
     191:	ff 15 be 08 00 00    	call   *0x8be(%rip)        # 0xa55
     197:	48 89 44 24 38       	mov    %rax,0x38(%rsp)
     19c:	48 83 f8 ff          	cmp    $0xffffffffffffffff,%rax
     1a0:	0f 84 a0 00 00 00    	je     0x246
     1a6:	4c 89 74 24 70       	mov    %r14,0x70(%rsp)
     1ab:	83 7c 24 64 00       	cmpl   $0x0,0x64(%rsp)
     1b0:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     1b5:	4c 8b 44 24 10       	mov    0x10(%rsp),%r8
     1ba:	4c 8b 4c 24 28       	mov    0x28(%rsp),%r9
     1bf:	4c 8b 64 24 30       	mov    0x30(%rsp),%r12
     1c4:	4c 8b 74 24 58       	mov    0x58(%rsp),%r14
     1c9:	4c 8b 6c 24 20       	mov    0x20(%rsp),%r13
     1ce:	0f 85 97 03 00 00    	jne    0x56b
     1d4:	49 8b 57 20          	mov    0x20(%r15),%rdx
     1d8:	48 83 fa 02          	cmp    $0x2,%rdx
     1dc:	0f 8c 89 03 00 00    	jl     0x56b
     1e2:	49 8b 45 00          	mov    0x0(%r13),%rax
     1e6:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     1ea:	4c 8b 98 a8 00 00 00 	mov    0xa8(%rax),%r11
     1f1:	49 8b 4f 10          	mov    0x10(%r15),%rcx
     1f5:	41 8a 7c 24 22       	mov    0x22(%r12),%dil
     1fa:	40 84 ff             	test   %dil,%dil
     1fd:	41 0f 94 c2          	sete   %r10b
     201:	49 8b 41 18          	mov    0x18(%r9),%rax
     205:	4c 89 5c 24 40       	mov    %r11,0x40(%rsp)
     20a:	4c 39 d8             	cmp    %r11,%rax
     20d:	0f 95 c0             	setne  %al
     210:	41 89 c3             	mov    %eax,%r11d
     213:	44 89 54 24 0c       	mov    %r10d,0xc(%rsp)
     218:	44 08 d0             	or     %r10b,%al
     21b:	a8 01                	test   $0x1,%al
     21d:	74 5d                	je     0x27c
     21f:	48 89 4c 24 68       	mov    %rcx,0x68(%rsp)
     224:	b8 01 00 00 00       	mov    $0x1,%eax
     229:	45 31 d2             	xor    %r10d,%r10d
     22c:	48 c7 44 24 40 00 00 	movq   $0x0,0x40(%rsp)
     233:	00 00 
     235:	48 c7 44 24 48 00 00 	movq   $0x0,0x48(%rsp)
     23c:	00 00 
     23e:	44 89 d9             	mov    %r11d,%ecx
     241:	e9 e8 00 00 00       	jmp    0x32e
     246:	ff 15 11 08 00 00    	call   *0x811(%rip)        # 0xa5d
     24c:	48 85 c0             	test   %rax,%rax
     24f:	0f 84 51 ff ff ff    	je     0x1a6
     255:	4c 8b 64 24 30       	mov    0x30(%rsp),%r12
     25a:	4c 8b 6c 24 20       	mov    0x20(%rsp),%r13
     25f:	4c 8b 7c 24 28       	mov    0x28(%rsp),%r15
     264:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
     269:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     26e:	48 8b 54 24 50       	mov    0x50(%rsp),%rdx
     273:	48 83 c4 78          	add    $0x78,%rsp
     277:	e9 7b 06 00 00       	jmp    0x8f7
     27c:	4c 8d 42 ff          	lea    -0x1(%rdx),%r8
     280:	48 8d 34 0a          	lea    (%rdx,%rcx,1),%rsi
     284:	48 83 c6 fe          	add    $0xfffffffffffffffe,%rsi
     288:	48 8d 04 0a          	lea    (%rdx,%rcx,1),%rax
     28c:	48 ff c8             	dec    %rax
     28f:	48 89 44 24 68       	mov    %rax,0x68(%rsp)
     294:	48 83 c2 fe          	add    $0xfffffffffffffffe,%rdx
     298:	b8 01 00 00 00       	mov    $0x1,%eax
     29d:	45 31 f6             	xor    %r14d,%r14d
     2a0:	45 31 d2             	xor    %r10d,%r10d
     2a3:	49 89 cb             	mov    %rcx,%r11
     2a6:	4c 8b 4c 24 38       	mov    0x38(%rsp),%r9
     2ab:	4e 8d 24 31          	lea    (%rcx,%r14,1),%r12
     2af:	4d 01 cc             	add    %r9,%r12
     2b2:	4c 89 64 24 38       	mov    %r12,0x38(%rsp)
     2b7:	41 0f 90 c5          	seto   %r13b
     2bb:	70 77                	jo     0x334
     2bd:	4c 39 f2             	cmp    %r14,%rdx
     2c0:	0f 84 86 00 00 00    	je     0x34c
     2c6:	4c 8b 4c 24 28       	mov    0x28(%rsp),%r9
     2cb:	4d 8b 49 18          	mov    0x18(%r9),%r9
     2cf:	49 ff c6             	inc    %r14
     2d2:	4c 3b 4c 24 40       	cmp    0x40(%rsp),%r9
     2d7:	41 0f 95 c4          	setne  %r12b
     2db:	75 13                	jne    0x2f0
     2dd:	4d 89 da             	mov    %r11,%r10
     2e0:	49 ff c3             	inc    %r11
     2e3:	48 ff c0             	inc    %rax
     2e6:	4c 8b 4c 24 38       	mov    0x38(%rsp),%r9
     2eb:	40 84 ff             	test   %dil,%dil
     2ee:	75 bb                	jne    0x2ab
     2f0:	4c 89 6c 24 48       	mov    %r13,0x48(%rsp)
     2f5:	49 8d 46 01          	lea    0x1(%r14),%rax
     2f9:	4e 8d 14 31          	lea    (%rcx,%r14,1),%r10
     2fd:	49 ff ca             	dec    %r10
     300:	4c 89 74 24 40       	mov    %r14,0x40(%rsp)
     305:	4c 01 f1             	add    %r14,%rcx
     308:	48 89 4c 24 68       	mov    %rcx,0x68(%rsp)
     30d:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     312:	4c 8b 44 24 10       	mov    0x10(%rsp),%r8
     317:	4c 8b 4c 24 28       	mov    0x28(%rsp),%r9
     31c:	44 89 e1             	mov    %r12d,%ecx
     31f:	4c 8b 64 24 30       	mov    0x30(%rsp),%r12
     324:	4c 8b 74 24 58       	mov    0x58(%rsp),%r14
     329:	4c 8b 6c 24 20       	mov    0x20(%rsp),%r13
     32e:	8b 54 24 0c          	mov    0xc(%rsp),%edx
     332:	eb 4a                	jmp    0x37e
     334:	4c 89 6c 24 48       	mov    %r13,0x48(%rsp)
     339:	4c 89 74 24 40       	mov    %r14,0x40(%rsp)
     33e:	31 c9                	xor    %ecx,%ecx
     340:	4c 89 5c 24 68       	mov    %r11,0x68(%rsp)
     345:	4c 89 4c 24 38       	mov    %r9,0x38(%rsp)
     34a:	eb 12                	jmp    0x35e
     34c:	4c 89 6c 24 48       	mov    %r13,0x48(%rsp)
     351:	31 c9                	xor    %ecx,%ecx
     353:	4c 89 c0             	mov    %r8,%rax
     356:	49 89 f2             	mov    %rsi,%r10
     359:	4c 89 44 24 40       	mov    %r8,0x40(%rsp)
     35e:	31 d2                	xor    %edx,%edx
     360:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     365:	4c 8b 44 24 10       	mov    0x10(%rsp),%r8
     36a:	4c 8b 4c 24 28       	mov    0x28(%rsp),%r9
     36f:	4c 8b 64 24 30       	mov    0x30(%rsp),%r12
     374:	4c 8b 74 24 58       	mov    0x58(%rsp),%r14
     379:	4c 8b 6c 24 20       	mov    0x20(%rsp),%r13
     37e:	08 d1                	or     %dl,%cl
     380:	49 01 84 24 c0 00 00 	add    %rax,0xc0(%r12)
     387:	00 
     388:	89 4c 24 0c          	mov    %ecx,0xc(%rsp)
     38c:	f6 c1 01             	test   $0x1,%cl
     38f:	74 08                	je     0x399
     391:	49 ff 84 24 c8 00 00 	incq   0xc8(%r12)
     398:	00 
     399:	48 83 7c 24 40 00    	cmpq   $0x0,0x40(%rsp)
     39f:	0f 84 26 01 00 00    	je     0x4cb
     3a5:	4d 89 d4             	mov    %r10,%r12
     3a8:	4d 89 06             	mov    %r8,(%r14)
     3ab:	49 89 76 08          	mov    %rsi,0x8(%r14)
     3af:	4c 8b 74 24 70       	mov    0x70(%rsp),%r14
     3b4:	4d 89 75 40          	mov    %r14,0x40(%r13)
     3b8:	48 8b 7c 24 38       	mov    0x38(%rsp),%rdi
     3bd:	ff 15 a2 06 00 00    	call   *0x6a2(%rip)        # 0xa65
     3c3:	48 85 c0             	test   %rax,%rax
     3c6:	0f 84 2d 01 00 00    	je     0x4f9
     3cc:	48 89 44 24 38       	mov    %rax,0x38(%rsp)
     3d1:	4c 89 e7             	mov    %r12,%rdi
     3d4:	ff 15 63 06 00 00    	call   *0x663(%rip)        # 0xa3d
     3da:	48 85 c0             	test   %rax,%rax
     3dd:	0f 84 20 01 00 00    	je     0x503
     3e3:	48 b9 23 00 00 00 00 	movabs $0x23,%rcx
     3ea:	00 00 00 
     3ed:	83 e1 0f             	and    $0xf,%ecx
     3f0:	4c 8b 6c 24 20       	mov    0x20(%rsp),%r13
     3f5:	49 8b 7c dd 50       	mov    0x50(%r13,%rbx,8),%rdi
     3fa:	89 c9                	mov    %ecx,%ecx
     3fc:	4d 8b 64 cd 50       	mov    0x50(%r13,%rcx,8),%r12
     401:	48 8b 74 24 38       	mov    0x38(%rsp),%rsi
     406:	0f b7 56 06          	movzwl 0x6(%rsi),%edx
     40a:	83 e2 01             	and    $0x1,%edx
     40d:	48 09 f2             	or     %rsi,%rdx
     410:	49 89 54 dd 50       	mov    %rdx,0x50(%r13,%rbx,8)
     415:	0f b7 50 06          	movzwl 0x6(%rax),%edx
     419:	83 e2 01             	and    $0x1,%edx
     41c:	48 09 c2             	or     %rax,%rdx
     41f:	49 89 54 cd 50       	mov    %rdx,0x50(%r13,%rcx,8)
     424:	40 f6 c7 01          	test   $0x1,%dil
     428:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     42d:	4c 8b 44 24 10       	mov    0x10(%rsp),%r8
     432:	75 19                	jne    0x44d
     434:	ff 0f                	decl   (%rdi)
     436:	75 15                	jne    0x44d
     438:	ff 15 df 05 00 00    	call   *0x5df(%rip)        # 0xa1d
     43e:	4c 8b 6c 24 20       	mov    0x20(%rsp),%r13
     443:	4c 8b 44 24 10       	mov    0x10(%rsp),%r8
     448:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     44d:	41 f6 c4 01          	test   $0x1,%r12b
     451:	48 8b 5c 24 68       	mov    0x68(%rsp),%rbx
     456:	4c 8b 74 24 40       	mov    0x40(%rsp),%r14
     45b:	75 1e                	jne    0x47b
     45d:	41 ff 0c 24          	decl   (%r12)
     461:	75 18                	jne    0x47b
     463:	4c 89 e7             	mov    %r12,%rdi
     466:	ff 15 b1 05 00 00    	call   *0x5b1(%rip)        # 0xa1d
     46c:	4c 8b 6c 24 20       	mov    0x20(%rsp),%r13
     471:	4c 8b 44 24 10       	mov    0x10(%rsp),%r8
     476:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     47b:	49 89 5f 10          	mov    %rbx,0x10(%r15)
     47f:	4d 29 77 20          	sub    %r14,0x20(%r15)
     483:	4c 8b 64 24 30       	mov    0x30(%rsp),%r12
     488:	49 ff 84 24 b0 00 00 	incq   0xb0(%r12)
     48f:	00 
     490:	4d 01 b4 24 b8 00 00 	add    %r14,0xb8(%r12)
     497:	00 
     498:	f6 44 24 0c 01       	testb  $0x1,0xc(%rsp)
     49d:	0f 84 a7 00 00 00    	je     0x54a
     4a3:	49 ff 84 24 e0 00 00 	incq   0xe0(%r12)
     4aa:	00 
     4ab:	80 7c 24 48 00       	cmpb   $0x0,0x48(%rsp)
     4b0:	48 8b 54 24 50       	mov    0x50(%rsp),%rdx
     4b5:	4c 8b 4c 24 28       	mov    0x28(%rsp),%r9
     4ba:	4c 8b 74 24 58       	mov    0x58(%rsp),%r14
     4bf:	74 29                	je     0x4ea
     4c1:	49 ff 84 24 d0 00 00 	incq   0xd0(%r12)
     4c8:	00 
     4c9:	eb 1f                	jmp    0x4ea
     4cb:	80 7c 24 48 00       	cmpb   $0x0,0x48(%rsp)
     4d0:	74 08                	je     0x4da
     4d2:	49 ff 84 24 d0 00 00 	incq   0xd0(%r12)
     4d9:	00 
     4da:	f6 44 24 0c 01       	testb  $0x1,0xc(%rsp)
     4df:	48 8b 54 24 50       	mov    0x50(%rsp),%rdx
     4e4:	0f 84 81 00 00 00    	je     0x56b
     4ea:	4d 89 cf             	mov    %r9,%r15
     4ed:	4c 89 c7             	mov    %r8,%rdi
     4f0:	48 83 c4 78          	add    $0x78,%rsp
     4f4:	e9 ae 03 00 00       	jmp    0x8a7
     4f9:	4c 8b 64 24 30       	mov    0x30(%rsp),%r12
     4fe:	e9 5c fd ff ff       	jmp    0x25f
     503:	48 8b 4c 24 38       	mov    0x38(%rsp),%rcx
     508:	8b 01                	mov    (%rcx),%eax
     50a:	85 c0                	test   %eax,%eax
     50c:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     511:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
     516:	4c 8b 6c 24 20       	mov    0x20(%rsp),%r13
     51b:	78 1e                	js     0x53b
     51d:	ff c8                	dec    %eax
     51f:	89 01                	mov    %eax,(%rcx)
     521:	75 18                	jne    0x53b
     523:	48 89 cf             	mov    %rcx,%rdi
     526:	ff 15 f1 04 00 00    	call   *0x4f1(%rip)        # 0xa1d
     52c:	4c 8b 6c 24 20       	mov    0x20(%rsp),%r13
     531:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
     536:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     53b:	4c 8b 64 24 30       	mov    0x30(%rsp),%r12
     540:	4c 8b 7c 24 28       	mov    0x28(%rsp),%r15
     545:	e9 24 fd ff ff       	jmp    0x26e
     54a:	49 ff 84 24 d8 00 00 	incq   0xd8(%r12)
     551:	00 
     552:	80 7c 24 48 00       	cmpb   $0x0,0x48(%rsp)
     557:	4c 8b 4c 24 28       	mov    0x28(%rsp),%r9
     55c:	4c 8b 74 24 58       	mov    0x58(%rsp),%r14
     561:	74 08                	je     0x56b
     563:	49 ff 84 24 d0 00 00 	incq   0xd0(%r12)
     56a:	00 
     56b:	4d 89 cf             	mov    %r9,%r15
     56e:	4c 89 c7             	mov    %r8,%rdi
     571:	31 d2                	xor    %edx,%edx
     573:	48 83 c4 78          	add    $0x78,%rsp
     577:	48 83 ec 18          	sub    $0x18,%rsp
     57b:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
     580:	48 89 74 24 08       	mov    %rsi,0x8(%rsp)
     585:	48 89 fb             	mov    %rdi,%rbx
     588:	48 89 f8             	mov    %rdi,%rax
     58b:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     58f:	48 8b 78 10          	mov    0x10(%rax),%rdi
     593:	48 8b 48 18          	mov    0x18(%rax),%rcx
     597:	48 01 f9             	add    %rdi,%rcx
     59a:	48 89 48 10          	mov    %rcx,0x10(%rax)
     59e:	48 ff 48 20          	decq   0x20(%rax)
     5a2:	ff 15 95 04 00 00    	call   *0x495(%rip)        # 0xa3d
     5a8:	48 85 c0             	test   %rax,%rax
     5ab:	74 18                	je     0x5c5
     5ad:	0f b7 50 06          	movzwl 0x6(%rax),%edx
     5b1:	83 e2 01             	and    $0x1,%edx
     5b4:	48 09 c2             	or     %rax,%rdx
     5b7:	48 89 df             	mov    %rbx,%rdi
     5ba:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     5bf:	48 83 c4 18          	add    $0x18,%rsp
     5c3:	eb 21                	jmp    0x5e6
     5c5:	49 89 1e             	mov    %rbx,(%r14)
     5c8:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     5cd:	49 89 76 08          	mov    %rsi,0x8(%r14)
     5d1:	49 83 c6 10          	add    $0x10,%r14
     5d5:	48 89 df             	mov    %rbx,%rdi
     5d8:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
     5dd:	48 83 c4 18          	add    $0x18,%rsp
     5e1:	e9 45 03 00 00       	jmp    0x92b
     5e6:	48 b8 6c a8 4a 88 cd 	movabs $0x7fcd884aa86c,%rax
     5ed:	7f 00 00 
     5f0:	49 89 45 38          	mov    %rax,0x38(%r13)
     5f4:	49 8b 45 68          	mov    0x68(%r13),%rax
     5f8:	49 89 55 68          	mov    %rdx,0x68(%r13)
     5fc:	48 89 c2             	mov    %rax,%rdx
     5ff:	49 89 3e             	mov    %rdi,(%r14)
     602:	49 89 76 08          	mov    %rsi,0x8(%r14)
     606:	49 83 c6 10          	add    $0x10,%r14
     60a:	48 89 d7             	mov    %rdx,%rdi
     60d:	4d 89 75 40          	mov    %r14,0x40(%r13)
     611:	40 f6 c7 01          	test   $0x1,%dil
     615:	75 0f                	jne    0x626
     617:	ff 0f                	decl   (%rdi)
     619:	75 0b                	jne    0x626
     61b:	50                   	push   %rax
     61c:	ff 15 fb 03 00 00    	call   *0x3fb(%rip)        # 0xa1d
     622:	48 83 c4 08          	add    $0x8,%rsp
     626:	31 ff                	xor    %edi,%edi
     628:	31 f6                	xor    %esi,%esi
     62a:	31 d2                	xor    %edx,%edx
     62c:	49 8b 7d 60          	mov    0x60(%r13),%rdi
     630:	40 f6 c7 01          	test   $0x1,%dil
     634:	75 02                	jne    0x638
     636:	ff 07                	incl   (%rdi)
     638:	41 80 7c 24 22 00    	cmpb   $0x0,0x22(%r12)
     63e:	0f 84 1b 03 00 00    	je     0x95f
     644:	49 8b 75 68          	mov    0x68(%r13),%rsi
     648:	48 83 ce 01          	or     $0x1,%rsi
     64c:	48 89 f0             	mov    %rsi,%rax
     64f:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     653:	48 83 78 10 10       	cmpq   $0x10,0x10(%rax)
     658:	0f 83 4b 03 00 00    	jae    0x9a9
     65e:	48 89 f8             	mov    %rdi,%rax
     661:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     665:	48 b9 00 8c 14 68 09 	movabs $0x560968148c00,%rcx
     66c:	56 00 00 
     66f:	48 39 48 08          	cmp    %rcx,0x8(%rax)
     673:	0f 85 30 03 00 00    	jne    0x9a9
     679:	48 83 78 10 10       	cmpq   $0x10,0x10(%rax)
     67e:	0f 83 25 03 00 00    	jae    0x9a9
     684:	48 83 ec 18          	sub    $0x18,%rsp
     688:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
     68d:	48 89 fb             	mov    %rdi,%rbx
     690:	48 83 e7 fe          	and    $0xfffffffffffffffe,%rdi
     694:	48 89 74 24 08       	mov    %rsi,0x8(%rsp)
     699:	48 83 e6 fe          	and    $0xfffffffffffffffe,%rsi
     69d:	ff 15 82 03 00 00    	call   *0x382(%rip)        # 0xa25
     6a3:	48 83 f8 01          	cmp    $0x1,%rax
     6a7:	75 16                	jne    0x6bf
     6a9:	48 89 df             	mov    %rbx,%rdi
     6ac:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     6b1:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
     6b6:	48 83 c4 18          	add    $0x18,%rsp
     6ba:	e9 ea 02 00 00       	jmp    0x9a9
     6bf:	48 89 c7             	mov    %rax,%rdi
     6c2:	48 89 de             	mov    %rbx,%rsi
     6c5:	48 8b 54 24 08       	mov    0x8(%rsp),%rdx
     6ca:	48 83 c4 18          	add    $0x18,%rsp
     6ce:	48 89 f3             	mov    %rsi,%rbx
     6d1:	f6 c3 01             	test   $0x1,%bl
     6d4:	75 52                	jne    0x728
     6d6:	ff 0b                	decl   (%rbx)
     6d8:	75 4e                	jne    0x728
     6da:	48 83 ec 18          	sub    $0x18,%rsp
     6de:	48 89 7c 24 08       	mov    %rdi,0x8(%rsp)
     6e3:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
     6e8:	48 b8 30 f2 17 68 09 	movabs $0x56096817f230,%rax
     6ef:	56 00 00 
     6f2:	48 8b 00             	mov    (%rax),%rax
     6f5:	48 85 c0             	test   %rax,%rax
     6f8:	74 17                	je     0x711
     6fa:	48 b9 38 f2 17 68 09 	movabs $0x56096817f238,%rcx
     701:	56 00 00 
     704:	48 8b 11             	mov    (%rcx),%rdx
     707:	48 89 df             	mov    %rbx,%rdi
     70a:	be 01 00 00 00       	mov    $0x1,%esi
     70f:	ff d0                	call   *%rax
     711:	48 89 df             	mov    %rbx,%rdi
     714:	ff 15 2b 03 00 00    	call   *0x32b(%rip)        # 0xa45
     71a:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
     71f:	48 8b 7c 24 08       	mov    0x8(%rsp),%rdi
     724:	48 83 c4 18          	add    $0x18,%rsp
     728:	48 89 de             	mov    %rbx,%rsi
     72b:	49 8b 45 60          	mov    0x60(%r13),%rax
     72f:	49 89 7d 60          	mov    %rdi,0x60(%r13)
     733:	48 89 c7             	mov    %rax,%rdi
     736:	48 89 fb             	mov    %rdi,%rbx
     739:	f6 c3 01             	test   $0x1,%bl
     73c:	75 52                	jne    0x790
     73e:	ff 0b                	decl   (%rbx)
     740:	75 4e                	jne    0x790
     742:	48 83 ec 18          	sub    $0x18,%rsp
     746:	48 89 74 24 08       	mov    %rsi,0x8(%rsp)
     74b:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
     750:	48 b8 30 f2 17 68 09 	movabs $0x56096817f230,%rax
     757:	56 00 00 
     75a:	48 8b 00             	mov    (%rax),%rax
     75d:	48 85 c0             	test   %rax,%rax
     760:	74 17                	je     0x779
     762:	48 b9 38 f2 17 68 09 	movabs $0x56096817f238,%rcx
     769:	56 00 00 
     76c:	48 8b 11             	mov    (%rcx),%rdx
     76f:	48 89 df             	mov    %rbx,%rdi
     772:	be 01 00 00 00       	mov    $0x1,%esi
     777:	ff d0                	call   *%rax
     779:	48 89 df             	mov    %rbx,%rdi
     77c:	ff 15 c3 02 00 00    	call   *0x2c3(%rip)        # 0xa45
     782:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
     787:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     78c:	48 83 c4 18          	add    $0x18,%rsp
     790:	48 89 df             	mov    %rbx,%rdi
     793:	e9 b4 f8 ff ff       	jmp    0x4c
     798:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     79f:	00 00 00 00 
     7a3:	4d 89 75 40          	mov    %r14,0x40(%r13)
     7a7:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     7ac:	75 0e                	jne    0x7bc
     7ae:	48 b8 c0 b9 15 68 09 	movabs $0x56096815b9c0,%rax
     7b5:	56 00 00 
     7b8:	48 8b 00             	mov    (%rax),%rax
     7bb:	c3                   	ret
     7bc:	49 8b 45 00          	mov    0x0(%r13),%rax
     7c0:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     7c4:	48 b9 1b 00 00 00 00 	movabs $0x1b,%rcx
     7cb:	00 00 00 
     7ce:	89 c9                	mov    %ecx,%ecx
     7d0:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     7d4:	48 05 c8 00 00 00    	add    $0xc8,%rax
     7da:	c3                   	ret
     7db:	49 8b 45 00          	mov    0x0(%r13),%rax
     7df:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     7e3:	48 b9 1b 00 00 00 00 	movabs $0x1b,%rcx
     7ea:	00 00 00 
     7ed:	89 c9                	mov    %ecx,%ecx
     7ef:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     7f3:	48 05 c8 00 00 00    	add    $0xc8,%rax
     7f9:	49 89 45 38          	mov    %rax,0x38(%r13)
     7fd:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     804:	00 00 00 00 
     808:	4d 89 75 40          	mov    %r14,0x40(%r13)
     80c:	31 c0                	xor    %eax,%eax
     80e:	c3                   	ret
     80f:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     816:	00 00 00 00 
     81a:	4d 89 75 40          	mov    %r14,0x40(%r13)
     81e:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     823:	75 0e                	jne    0x833
     825:	48 b8 c0 b9 15 68 09 	movabs $0x56096815b9c0,%rax
     82c:	56 00 00 
     82f:	48 8b 00             	mov    (%rax),%rax
     832:	c3                   	ret
     833:	49 8b 45 00          	mov    0x0(%r13),%rax
     837:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     83b:	48 b9 10 00 00 00 00 	movabs $0x10,%rcx
     842:	00 00 00 
     845:	89 c9                	mov    %ecx,%ecx
     847:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     84b:	48 05 c8 00 00 00    	add    $0xc8,%rax
     851:	c3                   	ret
     852:	48 b8 b8 2c 82 8b 09 	movabs $0x56098b822cb8,%rax
     859:	56 00 00 
     85c:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     863:	48 b8 c0 2c 82 8b 09 	movabs $0x56098b822cc0,%rax
     86a:	56 00 00 
     86d:	4c 8b 20             	mov    (%rax),%r12
     870:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     875:	ff e0                	jmp    *%rax
     877:	48 b8 c8 2c 82 8b 09 	movabs $0x56098b822cc8,%rax
     87e:	56 00 00 
     881:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     888:	49 89 3e             	mov    %rdi,(%r14)
     88b:	49 89 76 08          	mov    %rsi,0x8(%r14)
     88f:	49 83 c6 10          	add    $0x10,%r14
     893:	48 b8 d0 2c 82 8b 09 	movabs $0x56098b822cd0,%rax
     89a:	56 00 00 
     89d:	4c 8b 20             	mov    (%rax),%r12
     8a0:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     8a5:	ff e0                	jmp    *%rax
     8a7:	50                   	push   %rax
     8a8:	49 89 3e             	mov    %rdi,(%r14)
     8ab:	49 89 76 08          	mov    %rsi,0x8(%r14)
     8af:	49 83 c6 10          	add    $0x10,%r14
     8b3:	4d 89 75 40          	mov    %r14,0x40(%r13)
     8b7:	4c 89 ff             	mov    %r15,%rdi
     8ba:	ff 15 6d 01 00 00    	call   *0x16d(%rip)        # 0xa2d
     8c0:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     8c7:	00 00 00 00 
     8cb:	4d 89 75 40          	mov    %r14,0x40(%r13)
     8cf:	85 c0                	test   %eax,%eax
     8d1:	74 04                	je     0x8d7
     8d3:	31 c0                	xor    %eax,%eax
     8d5:	eb 1e                	jmp    0x8f5
     8d7:	49 8b 45 00          	mov    0x0(%r13),%rax
     8db:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     8df:	48 b9 1b 00 00 00 00 	movabs $0x1b,%rcx
     8e6:	00 00 00 
     8e9:	89 c9                	mov    %ecx,%ecx
     8eb:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     8ef:	48 05 c8 00 00 00    	add    $0xc8,%rax
     8f5:	59                   	pop    %rcx
     8f6:	c3                   	ret
     8f7:	49 8b 45 00          	mov    0x0(%r13),%rax
     8fb:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     8ff:	48 b9 14 00 00 00 00 	movabs $0x14,%rcx
     906:	00 00 00 
     909:	89 c9                	mov    %ecx,%ecx
     90b:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     90f:	48 05 c8 00 00 00    	add    $0xc8,%rax
     915:	49 89 45 38          	mov    %rax,0x38(%r13)
     919:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     920:	00 00 00 00 
     924:	4d 89 75 40          	mov    %r14,0x40(%r13)
     928:	31 c0                	xor    %eax,%eax
     92a:	c3                   	ret
     92b:	49 8b 45 00          	mov    0x0(%r13),%rax
     92f:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     933:	48 b9 10 00 00 00 00 	movabs $0x10,%rcx
     93a:	00 00 00 
     93d:	89 c9                	mov    %ecx,%ecx
     93f:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     943:	48 05 c8 00 00 00    	add    $0xc8,%rax
     949:	49 89 45 38          	mov    %rax,0x38(%r13)
     94d:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     954:	00 00 00 00 
     958:	4d 89 75 40          	mov    %r14,0x40(%r13)
     95c:	31 c0                	xor    %eax,%eax
     95e:	c3                   	ret
     95f:	49 89 3e             	mov    %rdi,(%r14)
     962:	49 83 c6 08          	add    $0x8,%r14
     966:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     96d:	00 00 00 00 
     971:	4d 89 75 40          	mov    %r14,0x40(%r13)
     975:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     97a:	75 0e                	jne    0x98a
     97c:	48 b8 c0 b9 15 68 09 	movabs $0x56096815b9c0,%rax
     983:	56 00 00 
     986:	48 8b 00             	mov    (%rax),%rax
     989:	c3                   	ret
     98a:	49 8b 45 00          	mov    0x0(%r13),%rax
     98e:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     992:	48 b9 13 00 00 00 00 	movabs $0x13,%rcx
     999:	00 00 00 
     99c:	89 c9                	mov    %ecx,%ecx
     99e:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     9a2:	48 05 c8 00 00 00    	add    $0xc8,%rax
     9a8:	c3                   	ret
     9a9:	48 b8 d8 2c 82 8b 09 	movabs $0x56098b822cd8,%rax
     9b0:	56 00 00 
     9b3:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     9ba:	49 89 3e             	mov    %rdi,(%r14)
     9bd:	49 89 76 08          	mov    %rsi,0x8(%r14)
     9c1:	49 83 c6 10          	add    $0x10,%r14
     9c5:	48 b8 e0 2c 82 8b 09 	movabs $0x56098b822ce0,%rax
     9cc:	56 00 00 
     9cf:	4c 8b 20             	mov    (%rax),%r12
     9d2:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     9d7:	ff e0                	jmp    *%rax
     9d9:	50                   	push   %rax
     9da:	48 bf f5 d9 28 88 cd 	movabs $0x7fcd8828d9f5,%rdi
     9e1:	7f 00 00 
     9e4:	48 be 00 da 28 88 cd 	movabs $0x7fcd8828da00,%rsi
     9eb:	7f 00 00 
     9ee:	ff 15 41 00 00 00    	call   *0x41(%rip)        # 0xa35
     9f4:	00 5f 4a             	add    %bl,0x4a(%rdi)
     9f7:	49 54                	rex.WB push %r12
     9f9:	5f                   	pop    %rdi
     9fa:	45                   	rex.RB
     9fb:	4e 54                	rex.WRX push %rsp
     9fd:	52                   	push   %rdx
     9fe:	59                   	pop    %rcx
     9ff:	00 46 61             	add    %al,0x61(%rsi)
     a02:	74 61                	je     0xa65
     a04:	6c                   	insb   (%dx),%es:(%rdi)
     a05:	20 65 72             	and    %ah,0x72(%rbp)
     a08:	72 6f                	jb     0xa79
     a0a:	72 20                	jb     0xa2c
     a0c:	75 6f                	jne    0xa7d
     a0e:	70 20                	jo     0xa30
     a10:	65 78 65             	gs js  0xa78
     a13:	63 75 74             	movsxd 0x74(%rbp),%esi
     a16:	65 64 2e 00 00       	gs fs add %al,%fs:(%rax)
     a1b:	00 00                	add    %al,(%rax)
     a1d:	e0 40                	loopne 0xa5f
     a1f:	c7                   	(bad)
     a20:	67 09 56 00          	or     %edx,0x0(%esi)
     a24:	00 80 da c4 67 09    	add    %al,0x967c4da(%rax)
     a2a:	56                   	push   %rsi
     a2b:	00 00                	add    %al,(%rax)
     a2d:	e0 2b                	loopne 0xa5a
     a2f:	dc 67 09             	fsubl  0x9(%rdi)
     a32:	56                   	push   %rsi
     a33:	00 00                	add    %al,(%rax)
     a35:	90                   	nop
     a36:	0c e4                	or     $0xe4,%al
     a38:	67 09 56 00          	or     %edx,0x0(%esi)
     a3c:	00 d0                	add    %dl,%al
     a3e:	4b c4 67 09 56       	(bad)
     a43:	00 00                	add    %al,(%rax)
     a45:	80 8a c3 67 09 56 00 	orb    $0x0,0x560967c3(%rdx)
     a4c:	00 30                	add    %dh,(%rax)
     a4e:	0f e2 67 09          	psrad  0x9(%rdi),%mm4
     a52:	56                   	push   %rsi
     a53:	00 00                	add    %al,(%rax)
     a55:	60                   	(bad)
     a56:	ab                   	stos   %eax,%es:(%rdi)
     a57:	c4 67 09 56          	(bad)
     a5b:	00 00                	add    %al,(%rax)
     a5d:	50                   	push   %rax
     a5e:	c1 b8 67 09 56 00 00 	sarl   $0x0,0x560967(%rax)
     a65:	f0 a5                	lock movsl %ds:(%rsi),%es:(%rdi)
     a67:	c4 67 09 56          	(bad)
	...
