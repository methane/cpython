
Tools/jit/tier3_data/native_acceptance/sum.bin:     file format binary


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
      30:	ff 15 0e 0a 00 00    	call   *0xa0e(%rip)        # 0xa44
      36:	48 89 df             	mov    %rbx,%rdi
      39:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
      3e:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
      43:	48 83 c4 18          	add    $0x18,%rsp
      47:	e9 0c 07 00 00       	jmp    0x758
      4c:	41 c6 44 24 24 00    	movb   $0x0,0x24(%r12)
      52:	48 b8 7e e8 cf 1e 57 	movabs $0x7f571ecfe87e,%rax
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
      83:	ff 15 a3 09 00 00    	call   *0x9a3(%rip)        # 0xa2c
      89:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
      8e:	4c 89 e2             	mov    %r12,%rdx
      91:	4c 8b 64 24 08       	mov    0x8(%rsp),%r12
      96:	85 c0                	test   %eax,%eax
      98:	48 8d 64 24 18       	lea    0x18(%rsp),%rsp
      9d:	74 08                	je     0xa7
      9f:	48 89 de             	mov    %rbx,%rsi
      a2:	e9 f4 06 00 00       	jmp    0x79b
      a7:	31 ff                	xor    %edi,%edi
      a9:	31 f6                	xor    %esi,%esi
      ab:	31 d2                	xor    %edx,%edx
      ad:	41 80 7c 24 22 00    	cmpb   $0x0,0x22(%r12)
      b3:	0f 84 16 07 00 00    	je     0x7cf
      b9:	49 8b 46 f0          	mov    -0x10(%r14),%rax
      bd:	48 89 c1             	mov    %rax,%rcx
      c0:	48 83 e1 fe          	and    $0xfffffffffffffffe,%rcx
      c4:	49 b8 20 8c 4e 4f 4d 	movabs $0x564d4f4e8c20,%r8
      cb:	56 00 00 
      ce:	4c 39 41 08          	cmp    %r8,0x8(%rcx)
      d2:	0f 85 3a 07 00 00    	jne    0x812
      d8:	49 8b 76 f8          	mov    -0x8(%r14),%rsi
      dc:	49 83 c6 f0          	add    $0xfffffffffffffff0,%r14
      e0:	48 89 c7             	mov    %rax,%rdi
      e3:	48 89 f8             	mov    %rdi,%rax
      e6:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
      ea:	48 83 78 20 00       	cmpq   $0x0,0x20(%rax)
      ef:	0f 8e 42 07 00 00    	jle    0x837
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
     123:	48 b8 20 8c 4e 4f 4d 	movabs $0x564d4f4e8c20,%rax
     12a:	56 00 00 
     12d:	49 39 47 08          	cmp    %rax,0x8(%r15)
     131:	0f 85 34 04 00 00    	jne    0x56b
     137:	49 83 7f 18 01       	cmpq   $0x1,0x18(%r15)
     13c:	0f 85 29 04 00 00    	jne    0x56b
     142:	48 83 e7 fe          	and    $0xfffffffffffffffe,%rdi
     146:	48 b8 00 1c 4e 4f 4d 	movabs $0x564d4f4e1c00,%rax
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
     191:	ff 15 b5 08 00 00    	call   *0x8b5(%rip)        # 0xa4c
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
     246:	ff 15 08 08 00 00    	call   *0x808(%rip)        # 0xa54
     24c:	48 85 c0             	test   %rax,%rax
     24f:	0f 84 51 ff ff ff    	je     0x1a6
     255:	4c 8b 64 24 30       	mov    0x30(%rsp),%r12
     25a:	4c 8b 6c 24 20       	mov    0x20(%rsp),%r13
     25f:	4c 8b 7c 24 28       	mov    0x28(%rsp),%r15
     264:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
     269:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     26e:	48 8b 54 24 50       	mov    0x50(%rsp),%rdx
     273:	48 83 c4 78          	add    $0x78,%rsp
     277:	e9 3b 06 00 00       	jmp    0x8b7
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
     3bd:	ff 15 99 06 00 00    	call   *0x699(%rip)        # 0xa5c
     3c3:	48 85 c0             	test   %rax,%rax
     3c6:	0f 84 2d 01 00 00    	je     0x4f9
     3cc:	48 89 44 24 38       	mov    %rax,0x38(%rsp)
     3d1:	4c 89 e7             	mov    %r12,%rdi
     3d4:	ff 15 62 06 00 00    	call   *0x662(%rip)        # 0xa3c
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
     438:	ff 15 e6 05 00 00    	call   *0x5e6(%rip)        # 0xa24
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
     466:	ff 15 b8 05 00 00    	call   *0x5b8(%rip)        # 0xa24
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
     4f4:	e9 6e 03 00 00       	jmp    0x867
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
     526:	ff 15 f8 04 00 00    	call   *0x4f8(%rip)        # 0xa24
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
     5a2:	ff 15 94 04 00 00    	call   *0x494(%rip)        # 0xa3c
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
     5e1:	e9 05 03 00 00       	jmp    0x8eb
     5e6:	48 b8 6c e8 cf 1e 57 	movabs $0x7f571ecfe86c,%rax
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
     61c:	ff 15 02 04 00 00    	call   *0x402(%rip)        # 0xa24
     622:	48 83 c4 08          	add    $0x8,%rsp
     626:	31 ff                	xor    %edi,%edi
     628:	31 f6                	xor    %esi,%esi
     62a:	31 d2                	xor    %edx,%edx
     62c:	49 8b 7d 60          	mov    0x60(%r13),%rdi
     630:	40 f6 c7 01          	test   $0x1,%dil
     634:	75 02                	jne    0x638
     636:	ff 07                	incl   (%rdi)
     638:	41 80 7c 24 22 00    	cmpb   $0x0,0x22(%r12)
     63e:	0f 84 db 02 00 00    	je     0x91f
     644:	49 8b 75 68          	mov    0x68(%r13),%rsi
     648:	48 83 ce 01          	or     $0x1,%rsi
     64c:	48 b8 70 e8 cf 1e 57 	movabs $0x7f571ecfe870,%rax
     653:	7f 00 00 
     656:	49 89 45 38          	mov    %rax,0x38(%r13)
     65a:	48 83 ec 18          	sub    $0x18,%rsp
     65e:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
     663:	48 89 f0             	mov    %rsi,%rax
     666:	48 89 fb             	mov    %rdi,%rbx
     669:	4c 89 3c 24          	mov    %r15,(%rsp)
     66d:	48 83 e7 fe          	and    $0xfffffffffffffffe,%rdi
     671:	48 83 e6 fe          	and    $0xfffffffffffffffe,%rsi
     675:	49 89 1e             	mov    %rbx,(%r14)
     678:	48 89 44 24 08       	mov    %rax,0x8(%rsp)
     67d:	49 89 46 08          	mov    %rax,0x8(%r14)
     681:	4d 8d 7e 10          	lea    0x10(%r14),%r15
     685:	4d 89 7d 40          	mov    %r15,0x40(%r13)
     689:	48 b8 0d 00 00 00 00 	movabs $0xd,%rax
     690:	00 00 00 
     693:	0f b7 c0             	movzwl %ax,%eax
     696:	48 b9 c0 f5 48 4f 4d 	movabs $0x564d4f48f5c0,%rcx
     69d:	56 00 00 
     6a0:	ff 14 c1             	call   *(%rcx,%rax,8)
     6a3:	48 85 c0             	test   %rax,%rax
     6a6:	74 1c                	je     0x6c4
     6a8:	0f b7 78 06          	movzwl 0x6(%rax),%edi
     6ac:	83 e7 01             	and    $0x1,%edi
     6af:	48 09 c7             	or     %rax,%rdi
     6b2:	4c 8b 3c 24          	mov    (%rsp),%r15
     6b6:	48 89 de             	mov    %rbx,%rsi
     6b9:	48 8b 54 24 08       	mov    0x8(%rsp),%rdx
     6be:	48 83 c4 18          	add    $0x18,%rsp
     6c2:	eb 1d                	jmp    0x6e1
     6c4:	4d 89 fe             	mov    %r15,%r14
     6c7:	4c 8b 3c 24          	mov    (%rsp),%r15
     6cb:	48 89 df             	mov    %rbx,%rdi
     6ce:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     6d3:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
     6d8:	48 83 c4 18          	add    $0x18,%rsp
     6dc:	e9 88 02 00 00       	jmp    0x969
     6e1:	49 89 3e             	mov    %rdi,(%r14)
     6e4:	49 83 c6 08          	add    $0x8,%r14
     6e8:	48 89 f7             	mov    %rsi,%rdi
     6eb:	4d 89 75 40          	mov    %r14,0x40(%r13)
     6ef:	40 f6 c7 01          	test   $0x1,%dil
     6f3:	75 0f                	jne    0x704
     6f5:	ff 0f                	decl   (%rdi)
     6f7:	75 0b                	jne    0x704
     6f9:	50                   	push   %rax
     6fa:	ff 15 24 03 00 00    	call   *0x324(%rip)        # 0xa24
     700:	48 83 c4 08          	add    $0x8,%rsp
     704:	31 ff                	xor    %edi,%edi
     706:	31 f6                	xor    %esi,%esi
     708:	31 d2                	xor    %edx,%edx
     70a:	41 80 7c 24 22 00    	cmpb   $0x0,0x22(%r12)
     710:	0f 84 87 02 00 00    	je     0x99d
     716:	48 b8 7c e8 cf 1e 57 	movabs $0x7f571ecfe87c,%rax
     71d:	7f 00 00 
     720:	49 89 45 38          	mov    %rax,0x38(%r13)
     724:	49 8b 46 f8          	mov    -0x8(%r14),%rax
     728:	49 83 c6 f8          	add    $0xfffffffffffffff8,%r14
     72c:	49 8b 7d 60          	mov    0x60(%r13),%rdi
     730:	49 89 45 60          	mov    %rax,0x60(%r13)
     734:	4d 89 75 40          	mov    %r14,0x40(%r13)
     738:	40 f6 c7 01          	test   $0x1,%dil
     73c:	75 0f                	jne    0x74d
     73e:	ff 0f                	decl   (%rdi)
     740:	75 0b                	jne    0x74d
     742:	50                   	push   %rax
     743:	ff 15 db 02 00 00    	call   *0x2db(%rip)        # 0xa24
     749:	48 83 c4 08          	add    $0x8,%rsp
     74d:	31 ff                	xor    %edi,%edi
     74f:	31 f6                	xor    %esi,%esi
     751:	31 d2                	xor    %edx,%edx
     753:	e9 f4 f8 ff ff       	jmp    0x4c
     758:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     75f:	00 00 00 00 
     763:	4d 89 75 40          	mov    %r14,0x40(%r13)
     767:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     76c:	75 0e                	jne    0x77c
     76e:	48 b8 c0 49 4f 4f 4d 	movabs $0x564d4f4f49c0,%rax
     775:	56 00 00 
     778:	48 8b 00             	mov    (%rax),%rax
     77b:	c3                   	ret
     77c:	49 8b 45 00          	mov    0x0(%r13),%rax
     780:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     784:	48 b9 1b 00 00 00 00 	movabs $0x1b,%rcx
     78b:	00 00 00 
     78e:	89 c9                	mov    %ecx,%ecx
     790:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     794:	48 05 c8 00 00 00    	add    $0xc8,%rax
     79a:	c3                   	ret
     79b:	49 8b 45 00          	mov    0x0(%r13),%rax
     79f:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     7a3:	48 b9 1b 00 00 00 00 	movabs $0x1b,%rcx
     7aa:	00 00 00 
     7ad:	89 c9                	mov    %ecx,%ecx
     7af:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     7b3:	48 05 c8 00 00 00    	add    $0xc8,%rax
     7b9:	49 89 45 38          	mov    %rax,0x38(%r13)
     7bd:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     7c4:	00 00 00 00 
     7c8:	4d 89 75 40          	mov    %r14,0x40(%r13)
     7cc:	31 c0                	xor    %eax,%eax
     7ce:	c3                   	ret
     7cf:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     7d6:	00 00 00 00 
     7da:	4d 89 75 40          	mov    %r14,0x40(%r13)
     7de:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     7e3:	75 0e                	jne    0x7f3
     7e5:	48 b8 c0 49 4f 4f 4d 	movabs $0x564d4f4f49c0,%rax
     7ec:	56 00 00 
     7ef:	48 8b 00             	mov    (%rax),%rax
     7f2:	c3                   	ret
     7f3:	49 8b 45 00          	mov    0x0(%r13),%rax
     7f7:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     7fb:	48 b9 10 00 00 00 00 	movabs $0x10,%rcx
     802:	00 00 00 
     805:	89 c9                	mov    %ecx,%ecx
     807:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     80b:	48 05 c8 00 00 00    	add    $0xc8,%rax
     811:	c3                   	ret
     812:	48 b8 18 75 49 8b 4d 	movabs $0x564d8b497518,%rax
     819:	56 00 00 
     81c:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     823:	48 b8 20 75 49 8b 4d 	movabs $0x564d8b497520,%rax
     82a:	56 00 00 
     82d:	4c 8b 20             	mov    (%rax),%r12
     830:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     835:	ff e0                	jmp    *%rax
     837:	48 b8 28 75 49 8b 4d 	movabs $0x564d8b497528,%rax
     83e:	56 00 00 
     841:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     848:	49 89 3e             	mov    %rdi,(%r14)
     84b:	49 89 76 08          	mov    %rsi,0x8(%r14)
     84f:	49 83 c6 10          	add    $0x10,%r14
     853:	48 b8 30 75 49 8b 4d 	movabs $0x564d8b497530,%rax
     85a:	56 00 00 
     85d:	4c 8b 20             	mov    (%rax),%r12
     860:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     865:	ff e0                	jmp    *%rax
     867:	50                   	push   %rax
     868:	49 89 3e             	mov    %rdi,(%r14)
     86b:	49 89 76 08          	mov    %rsi,0x8(%r14)
     86f:	49 83 c6 10          	add    $0x10,%r14
     873:	4d 89 75 40          	mov    %r14,0x40(%r13)
     877:	4c 89 ff             	mov    %r15,%rdi
     87a:	ff 15 ac 01 00 00    	call   *0x1ac(%rip)        # 0xa2c
     880:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     887:	00 00 00 00 
     88b:	4d 89 75 40          	mov    %r14,0x40(%r13)
     88f:	85 c0                	test   %eax,%eax
     891:	74 04                	je     0x897
     893:	31 c0                	xor    %eax,%eax
     895:	eb 1e                	jmp    0x8b5
     897:	49 8b 45 00          	mov    0x0(%r13),%rax
     89b:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     89f:	48 b9 1b 00 00 00 00 	movabs $0x1b,%rcx
     8a6:	00 00 00 
     8a9:	89 c9                	mov    %ecx,%ecx
     8ab:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     8af:	48 05 c8 00 00 00    	add    $0xc8,%rax
     8b5:	59                   	pop    %rcx
     8b6:	c3                   	ret
     8b7:	49 8b 45 00          	mov    0x0(%r13),%rax
     8bb:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     8bf:	48 b9 14 00 00 00 00 	movabs $0x14,%rcx
     8c6:	00 00 00 
     8c9:	89 c9                	mov    %ecx,%ecx
     8cb:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     8cf:	48 05 c8 00 00 00    	add    $0xc8,%rax
     8d5:	49 89 45 38          	mov    %rax,0x38(%r13)
     8d9:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     8e0:	00 00 00 00 
     8e4:	4d 89 75 40          	mov    %r14,0x40(%r13)
     8e8:	31 c0                	xor    %eax,%eax
     8ea:	c3                   	ret
     8eb:	49 8b 45 00          	mov    0x0(%r13),%rax
     8ef:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     8f3:	48 b9 10 00 00 00 00 	movabs $0x10,%rcx
     8fa:	00 00 00 
     8fd:	89 c9                	mov    %ecx,%ecx
     8ff:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     903:	48 05 c8 00 00 00    	add    $0xc8,%rax
     909:	49 89 45 38          	mov    %rax,0x38(%r13)
     90d:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     914:	00 00 00 00 
     918:	4d 89 75 40          	mov    %r14,0x40(%r13)
     91c:	31 c0                	xor    %eax,%eax
     91e:	c3                   	ret
     91f:	49 89 3e             	mov    %rdi,(%r14)
     922:	49 83 c6 08          	add    $0x8,%r14
     926:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     92d:	00 00 00 00 
     931:	4d 89 75 40          	mov    %r14,0x40(%r13)
     935:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     93a:	75 0e                	jne    0x94a
     93c:	48 b8 c0 49 4f 4f 4d 	movabs $0x564d4f4f49c0,%rax
     943:	56 00 00 
     946:	48 8b 00             	mov    (%rax),%rax
     949:	c3                   	ret
     94a:	49 8b 45 00          	mov    0x0(%r13),%rax
     94e:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     952:	48 b9 13 00 00 00 00 	movabs $0x13,%rcx
     959:	00 00 00 
     95c:	89 c9                	mov    %ecx,%ecx
     95e:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     962:	48 05 c8 00 00 00    	add    $0xc8,%rax
     968:	c3                   	ret
     969:	49 8b 45 00          	mov    0x0(%r13),%rax
     96d:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     971:	48 b9 14 00 00 00 00 	movabs $0x14,%rcx
     978:	00 00 00 
     97b:	89 c9                	mov    %ecx,%ecx
     97d:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     981:	48 05 c8 00 00 00    	add    $0xc8,%rax
     987:	49 89 45 38          	mov    %rax,0x38(%r13)
     98b:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     992:	00 00 00 00 
     996:	4d 89 75 40          	mov    %r14,0x40(%r13)
     99a:	31 c0                	xor    %eax,%eax
     99c:	c3                   	ret
     99d:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     9a4:	00 00 00 00 
     9a8:	4d 89 75 40          	mov    %r14,0x40(%r13)
     9ac:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     9b1:	75 0e                	jne    0x9c1
     9b3:	48 b8 c0 49 4f 4f 4d 	movabs $0x564d4f4f49c0,%rax
     9ba:	56 00 00 
     9bd:	48 8b 00             	mov    (%rax),%rax
     9c0:	c3                   	ret
     9c1:	49 8b 45 00          	mov    0x0(%r13),%rax
     9c5:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     9c9:	48 b9 1a 00 00 00 00 	movabs $0x1a,%rcx
     9d0:	00 00 00 
     9d3:	89 c9                	mov    %ecx,%ecx
     9d5:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     9d9:	48 05 c8 00 00 00    	add    $0xc8,%rax
     9df:	c3                   	ret
     9e0:	50                   	push   %rax
     9e1:	48 bf fc 39 9d 1e 57 	movabs $0x7f571e9d39fc,%rdi
     9e8:	7f 00 00 
     9eb:	48 be 07 3a 9d 1e 57 	movabs $0x7f571e9d3a07,%rsi
     9f2:	7f 00 00 
     9f5:	ff 15 39 00 00 00    	call   *0x39(%rip)        # 0xa34
     9fb:	00 5f 4a             	add    %bl,0x4a(%rdi)
     9fe:	49 54                	rex.WB push %r12
     a00:	5f                   	pop    %rdi
     a01:	45                   	rex.RB
     a02:	4e 54                	rex.WRX push %rsp
     a04:	52                   	push   %rdx
     a05:	59                   	pop    %rcx
     a06:	00 46 61             	add    %al,0x61(%rsi)
     a09:	74 61                	je     0xa6c
     a0b:	6c                   	insb   (%dx),%es:(%rdi)
     a0c:	20 65 72             	and    %ah,0x72(%rbp)
     a0f:	72 6f                	jb     0xa80
     a11:	72 20                	jb     0xa33
     a13:	75 6f                	jne    0xa84
     a15:	70 20                	jo     0xa37
     a17:	65 78 65             	gs js  0xa7f
     a1a:	63 75 74             	movsxd 0x74(%rbp),%esi
     a1d:	65 64 2e 00 00       	gs fs add %al,%fs:(%rax)
     a22:	00 00                	add    %al,(%rax)
     a24:	e0 c0                	loopne 0x9e6
     a26:	00 4f 4d             	add    %cl,0x4d(%rdi)
     a29:	56                   	push   %rsi
     a2a:	00 00                	add    %al,(%rax)
     a2c:	e0 ab                	loopne 0x9d9
     a2e:	15 4f 4d 56 00       	adc    $0x564d4f,%eax
     a33:	00 c0                	add    %al,%al
     a35:	8e 1d 4f 4d 56 00    	mov    0x564d4f(%rip),%ds        # 0x56578a
     a3b:	00 d0                	add    %dl,%al
     a3d:	cb                   	lret
     a3e:	fd                   	std
     a3f:	4e                   	rex.WRX
     a40:	4d 56                	rex.WRB push %r14
     a42:	00 00                	add    %al,(%rax)
     a44:	60                   	(bad)
     a45:	91                   	xchg   %eax,%ecx
     a46:	1b 4f 4d             	sbb    0x4d(%rdi),%ecx
     a49:	56                   	push   %rsi
     a4a:	00 00                	add    %al,(%rax)
     a4c:	60                   	(bad)
     a4d:	2b fe                	sub    %esi,%edi
     a4f:	4e                   	rex.WRX
     a50:	4d 56                	rex.WRB push %r14
     a52:	00 00                	add    %al,(%rax)
     a54:	50                   	push   %rax
     a55:	41                   	rex.B
     a56:	f2 4e                	repnz rex.WRX
     a58:	4d 56                	rex.WRB push %r14
     a5a:	00 00                	add    %al,(%rax)
     a5c:	f0 25 fe 4e 4d 56    	lock and $0x564d4efe,%eax
	...
