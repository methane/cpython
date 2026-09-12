
Tools/jit/tier3_data/native_followup/squares.bin:     file format binary


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
      30:	ff 15 1d 0c 00 00    	call   *0xc1d(%rip)        # 0xc53
      36:	48 89 df             	mov    %rbx,%rdi
      39:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
      3e:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
      43:	48 83 c4 18          	add    $0x18,%rsp
      47:	e9 ee 08 00 00       	jmp    0x93a
      4c:	41 c6 44 24 24 00    	movb   $0x0,0x24(%r12)
      52:	48 b8 9a 3a 47 88 cd 	movabs $0x7fcd88473a9a,%rax
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
      83:	ff 15 aa 0b 00 00    	call   *0xbaa(%rip)        # 0xc33
      89:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
      8e:	4c 89 e2             	mov    %r12,%rdx
      91:	4c 8b 64 24 08       	mov    0x8(%rsp),%r12
      96:	85 c0                	test   %eax,%eax
      98:	48 8d 64 24 18       	lea    0x18(%rsp),%rsp
      9d:	74 08                	je     0xa7
      9f:	48 89 de             	mov    %rbx,%rsi
      a2:	e9 d6 08 00 00       	jmp    0x97d
      a7:	31 ff                	xor    %edi,%edi
      a9:	31 f6                	xor    %esi,%esi
      ab:	31 d2                	xor    %edx,%edx
      ad:	41 80 7c 24 22 00    	cmpb   $0x0,0x22(%r12)
      b3:	0f 84 f8 08 00 00    	je     0x9b1
      b9:	49 8b 46 f0          	mov    -0x10(%r14),%rax
      bd:	48 89 c1             	mov    %rax,%rcx
      c0:	48 83 e1 fe          	and    $0xfffffffffffffffe,%rcx
      c4:	49 b8 20 fc 14 68 09 	movabs $0x56096814fc20,%r8
      cb:	56 00 00 
      ce:	4c 39 41 08          	cmp    %r8,0x8(%rcx)
      d2:	0f 85 1c 09 00 00    	jne    0x9f4
      d8:	49 8b 76 f8          	mov    -0x8(%r14),%rsi
      dc:	49 83 c6 f0          	add    $0xfffffffffffffff0,%r14
      e0:	48 89 c7             	mov    %rax,%rdi
      e3:	48 89 f8             	mov    %rdi,%rax
      e6:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
      ea:	48 83 78 20 00       	cmpq   $0x0,0x20(%rax)
      ef:	0f 8e 24 09 00 00    	jle    0xa19
      f5:	48 83 ec 78          	sub    $0x78,%rsp
      f9:	49 89 f8             	mov    %rdi,%r8
      fc:	48 b8 23 00 00 00 00 	movabs $0x23,%rax
     103:	00 00 00 
     106:	0f b7 d8             	movzwl %ax,%ebx
     109:	c1 eb 04             	shr    $0x4,%ebx
     10c:	48 89 f9             	mov    %rdi,%rcx
     10f:	48 83 e1 fe          	and    $0xfffffffffffffffe,%rcx
     113:	49 8b 7c dd 50       	mov    0x50(%r13,%rbx,8),%rdi
     118:	c7 44 24 64 00 00 00 	movl   $0x0,0x64(%rsp)
     11f:	00 
     120:	48 b8 20 fc 14 68 09 	movabs $0x56096814fc20,%rax
     127:	56 00 00 
     12a:	48 39 41 08          	cmp    %rax,0x8(%rcx)
     12e:	0f 85 64 04 00 00    	jne    0x598
     134:	48 83 79 18 01       	cmpq   $0x1,0x18(%rcx)
     139:	0f 85 59 04 00 00    	jne    0x598
     13f:	48 83 e7 fe          	and    $0xfffffffffffffffe,%rdi
     143:	48 b8 00 8c 14 68 09 	movabs $0x560968148c00,%rax
     14a:	56 00 00 
     14d:	48 39 47 08          	cmp    %rax,0x8(%rdi)
     151:	0f 85 41 04 00 00    	jne    0x598
     157:	48 89 4c 24 68       	mov    %rcx,0x68(%rsp)
     15c:	4c 89 64 24 28       	mov    %r12,0x28(%rsp)
     161:	4c 89 7c 24 20       	mov    %r15,0x20(%rsp)
     166:	48 89 54 24 48       	mov    %rdx,0x48(%rsp)
     16b:	4c 89 44 24 08       	mov    %r8,0x8(%rsp)
     170:	4d 89 06             	mov    %r8,(%r14)
     173:	48 89 74 24 18       	mov    %rsi,0x18(%rsp)
     178:	49 89 76 08          	mov    %rsi,0x8(%r14)
     17c:	4c 89 74 24 38       	mov    %r14,0x38(%rsp)
     181:	49 83 c6 10          	add    $0x10,%r14
     185:	4c 89 6c 24 10       	mov    %r13,0x10(%rsp)
     18a:	4d 89 75 40          	mov    %r14,0x40(%r13)
     18e:	48 8d 74 24 64       	lea    0x64(%rsp),%rsi
     193:	ff 15 c2 0a 00 00    	call   *0xac2(%rip)        # 0xc5b
     199:	49 89 c7             	mov    %rax,%r15
     19c:	48 83 f8 ff          	cmp    $0xffffffffffffffff,%rax
     1a0:	0f 84 ae 00 00 00    	je     0x254
     1a6:	4d 89 f9             	mov    %r15,%r9
     1a9:	4c 89 74 24 70       	mov    %r14,0x70(%rsp)
     1ae:	83 7c 24 64 00       	cmpl   $0x0,0x64(%rsp)
     1b3:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     1b8:	4c 8b 44 24 08       	mov    0x8(%rsp),%r8
     1bd:	4c 8b 7c 24 20       	mov    0x20(%rsp),%r15
     1c2:	4c 8b 64 24 28       	mov    0x28(%rsp),%r12
     1c7:	4c 8b 74 24 38       	mov    0x38(%rsp),%r14
     1cc:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     1d1:	48 8b 4c 24 68       	mov    0x68(%rsp),%rcx
     1d6:	0f 85 bc 03 00 00    	jne    0x598
     1dc:	48 8b 51 20          	mov    0x20(%rcx),%rdx
     1e0:	48 83 fa 02          	cmp    $0x2,%rdx
     1e4:	0f 8c ae 03 00 00    	jl     0x598
     1ea:	49 8b 45 00          	mov    0x0(%r13),%rax
     1ee:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     1f2:	4c 8b 90 a8 00 00 00 	mov    0xa8(%rax),%r10
     1f9:	48 8b 49 10          	mov    0x10(%rcx),%rcx
     1fd:	41 8a 7c 24 22       	mov    0x22(%r12),%dil
     202:	40 84 ff             	test   %dil,%dil
     205:	41 0f 94 c3          	sete   %r11b
     209:	49 8b 47 18          	mov    0x18(%r15),%rax
     20d:	4c 39 d0             	cmp    %r10,%rax
     210:	0f 95 c0             	setne  %al
     213:	89 44 24 30          	mov    %eax,0x30(%rsp)
     217:	44 89 5c 24 60       	mov    %r11d,0x60(%rsp)
     21c:	44 08 d8             	or     %r11b,%al
     21f:	a8 01                	test   $0x1,%al
     221:	74 67                	je     0x28a
     223:	48 89 4c 24 50       	mov    %rcx,0x50(%rsp)
     228:	b8 01 00 00 00       	mov    $0x1,%eax
     22d:	48 c7 44 24 58 00 00 	movq   $0x0,0x58(%rsp)
     234:	00 00 
     236:	48 c7 44 24 40 00 00 	movq   $0x0,0x40(%rsp)
     23d:	00 00 
     23f:	c7 44 24 04 00 00 00 	movl   $0x0,0x4(%rsp)
     246:	00 
     247:	8b 4c 24 30          	mov    0x30(%rsp),%ecx
     24b:	8b 54 24 60          	mov    0x60(%rsp),%edx
     24f:	e9 4d 01 00 00       	jmp    0x3a1
     254:	ff 15 09 0a 00 00    	call   *0xa09(%rip)        # 0xc63
     25a:	48 85 c0             	test   %rax,%rax
     25d:	0f 84 43 ff ff ff    	je     0x1a6
     263:	4c 8b 64 24 28       	mov    0x28(%rsp),%r12
     268:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     26d:	4c 8b 7c 24 20       	mov    0x20(%rsp),%r15
     272:	48 8b 7c 24 08       	mov    0x8(%rsp),%rdi
     277:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     27c:	48 8b 54 24 48       	mov    0x48(%rsp),%rdx
     281:	48 83 c4 78          	add    $0x78,%rsp
     285:	e9 f3 06 00 00       	jmp    0x97d
     28a:	4c 8d 42 ff          	lea    -0x1(%rdx),%r8
     28e:	48 8d 34 0a          	lea    (%rdx,%rcx,1),%rsi
     292:	48 83 c6 fe          	add    $0xfffffffffffffffe,%rsi
     296:	48 8d 04 0a          	lea    (%rdx,%rcx,1),%rax
     29a:	48 ff c8             	dec    %rax
     29d:	48 89 44 24 30       	mov    %rax,0x30(%rsp)
     2a2:	48 83 c2 fe          	add    $0xfffffffffffffffe,%rdx
     2a6:	b8 01 00 00 00       	mov    $0x1,%eax
     2ab:	45 31 f6             	xor    %r14d,%r14d
     2ae:	45 31 ed             	xor    %r13d,%r13d
     2b1:	49 89 cb             	mov    %rcx,%r11
     2b4:	4e 8d 24 31          	lea    (%rcx,%r14,1),%r12
     2b8:	4d 0f af e4          	imul   %r12,%r12
     2bc:	0f 80 82 00 00 00    	jo     0x344
     2c2:	4d 01 cc             	add    %r9,%r12
     2c5:	70 7d                	jo     0x344
     2c7:	4c 39 f2             	cmp    %r14,%rdx
     2ca:	0f 84 8d 00 00 00    	je     0x35d
     2d0:	4c 8b 4c 24 20       	mov    0x20(%rsp),%r9
     2d5:	4d 8b 49 18          	mov    0x18(%r9),%r9
     2d9:	49 ff c6             	inc    %r14
     2dc:	4d 39 d1             	cmp    %r10,%r9
     2df:	41 0f 95 c7          	setne  %r15b
     2e3:	75 11                	jne    0x2f6
     2e5:	4d 89 dd             	mov    %r11,%r13
     2e8:	49 ff c3             	inc    %r11
     2eb:	48 ff c0             	inc    %rax
     2ee:	4d 89 e1             	mov    %r12,%r9
     2f1:	40 84 ff             	test   %dil,%dil
     2f4:	75 be                	jne    0x2b4
     2f6:	4d 89 e1             	mov    %r12,%r9
     2f9:	49 8d 46 01          	lea    0x1(%r14),%rax
     2fd:	4a 8d 14 31          	lea    (%rcx,%r14,1),%rdx
     301:	48 ff ca             	dec    %rdx
     304:	48 89 54 24 58       	mov    %rdx,0x58(%rsp)
     309:	4c 89 74 24 40       	mov    %r14,0x40(%rsp)
     30e:	4c 01 f1             	add    %r14,%rcx
     311:	48 89 4c 24 50       	mov    %rcx,0x50(%rsp)
     316:	c7 44 24 04 00 00 00 	movl   $0x0,0x4(%rsp)
     31d:	00 
     31e:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     323:	4c 8b 44 24 08       	mov    0x8(%rsp),%r8
     328:	44 89 f9             	mov    %r15d,%ecx
     32b:	4c 8b 7c 24 20       	mov    0x20(%rsp),%r15
     330:	4c 8b 64 24 28       	mov    0x28(%rsp),%r12
     335:	4c 8b 74 24 38       	mov    0x38(%rsp),%r14
     33a:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     33f:	e9 07 ff ff ff       	jmp    0x24b
     344:	4c 89 6c 24 58       	mov    %r13,0x58(%rsp)
     349:	b1 01                	mov    $0x1,%cl
     34b:	89 4c 24 04          	mov    %ecx,0x4(%rsp)
     34f:	4c 89 74 24 40       	mov    %r14,0x40(%rsp)
     354:	31 c9                	xor    %ecx,%ecx
     356:	4c 89 5c 24 50       	mov    %r11,0x50(%rsp)
     35b:	eb 24                	jmp    0x381
     35d:	4d 89 e1             	mov    %r12,%r9
     360:	c7 44 24 04 00 00 00 	movl   $0x0,0x4(%rsp)
     367:	00 
     368:	4c 89 c0             	mov    %r8,%rax
     36b:	48 89 74 24 58       	mov    %rsi,0x58(%rsp)
     370:	4c 89 44 24 40       	mov    %r8,0x40(%rsp)
     375:	48 8b 4c 24 30       	mov    0x30(%rsp),%rcx
     37a:	48 89 4c 24 50       	mov    %rcx,0x50(%rsp)
     37f:	31 c9                	xor    %ecx,%ecx
     381:	31 d2                	xor    %edx,%edx
     383:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     388:	4c 8b 44 24 08       	mov    0x8(%rsp),%r8
     38d:	4c 8b 7c 24 20       	mov    0x20(%rsp),%r15
     392:	4c 8b 64 24 28       	mov    0x28(%rsp),%r12
     397:	4c 8b 74 24 38       	mov    0x38(%rsp),%r14
     39c:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     3a1:	08 d1                	or     %dl,%cl
     3a3:	49 01 84 24 c0 00 00 	add    %rax,0xc0(%r12)
     3aa:	00 
     3ab:	89 4c 24 30          	mov    %ecx,0x30(%rsp)
     3af:	f6 c1 01             	test   $0x1,%cl
     3b2:	74 08                	je     0x3bc
     3b4:	49 ff 84 24 c8 00 00 	incq   0xc8(%r12)
     3bb:	00 
     3bc:	48 83 7c 24 40 00    	cmpq   $0x0,0x40(%rsp)
     3c2:	0f 84 29 01 00 00    	je     0x4f1
     3c8:	4d 89 06             	mov    %r8,(%r14)
     3cb:	49 89 76 08          	mov    %rsi,0x8(%r14)
     3cf:	4c 8b 74 24 70       	mov    0x70(%rsp),%r14
     3d4:	4d 89 75 40          	mov    %r14,0x40(%r13)
     3d8:	4c 89 cf             	mov    %r9,%rdi
     3db:	49 89 f4             	mov    %rsi,%r12
     3de:	ff 15 87 08 00 00    	call   *0x887(%rip)        # 0xc6b
     3e4:	48 85 c0             	test   %rax,%rax
     3e7:	0f 84 2f 01 00 00    	je     0x51c
     3ed:	49 89 c7             	mov    %rax,%r15
     3f0:	48 8b 7c 24 58       	mov    0x58(%rsp),%rdi
     3f5:	ff 15 48 08 00 00    	call   *0x848(%rip)        # 0xc43
     3fb:	48 85 c0             	test   %rax,%rax
     3fe:	0f 84 2f 01 00 00    	je     0x533
     404:	48 b9 23 00 00 00 00 	movabs $0x23,%rcx
     40b:	00 00 00 
     40e:	83 e1 0f             	and    $0xf,%ecx
     411:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     416:	49 8b 7c dd 50       	mov    0x50(%r13,%rbx,8),%rdi
     41b:	89 c9                	mov    %ecx,%ecx
     41d:	4d 8b 64 cd 50       	mov    0x50(%r13,%rcx,8),%r12
     422:	41 0f b7 57 06       	movzwl 0x6(%r15),%edx
     427:	83 e2 01             	and    $0x1,%edx
     42a:	4c 09 fa             	or     %r15,%rdx
     42d:	49 89 54 dd 50       	mov    %rdx,0x50(%r13,%rbx,8)
     432:	0f b7 50 06          	movzwl 0x6(%rax),%edx
     436:	83 e2 01             	and    $0x1,%edx
     439:	48 09 c2             	or     %rax,%rdx
     43c:	49 89 54 cd 50       	mov    %rdx,0x50(%r13,%rcx,8)
     441:	40 f6 c7 01          	test   $0x1,%dil
     445:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     44a:	4c 8b 44 24 08       	mov    0x8(%rsp),%r8
     44f:	75 19                	jne    0x46a
     451:	ff 0f                	decl   (%rdi)
     453:	75 15                	jne    0x46a
     455:	ff 15 c0 07 00 00    	call   *0x7c0(%rip)        # 0xc1b
     45b:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     460:	4c 8b 44 24 08       	mov    0x8(%rsp),%r8
     465:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     46a:	41 f6 c4 01          	test   $0x1,%r12b
     46e:	48 8b 5c 24 50       	mov    0x50(%rsp),%rbx
     473:	4c 8b 74 24 40       	mov    0x40(%rsp),%r14
     478:	44 8b 7c 24 30       	mov    0x30(%rsp),%r15d
     47d:	75 1e                	jne    0x49d
     47f:	41 ff 0c 24          	decl   (%r12)
     483:	75 18                	jne    0x49d
     485:	4c 89 e7             	mov    %r12,%rdi
     488:	ff 15 8d 07 00 00    	call   *0x78d(%rip)        # 0xc1b
     48e:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     493:	4c 8b 44 24 08       	mov    0x8(%rsp),%r8
     498:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     49d:	48 8b 44 24 68       	mov    0x68(%rsp),%rax
     4a2:	48 89 58 10          	mov    %rbx,0x10(%rax)
     4a6:	4c 29 70 20          	sub    %r14,0x20(%rax)
     4aa:	4c 8b 64 24 28       	mov    0x28(%rsp),%r12
     4af:	49 ff 84 24 b0 00 00 	incq   0xb0(%r12)
     4b6:	00 
     4b7:	4d 01 b4 24 b8 00 00 	add    %r14,0xb8(%r12)
     4be:	00 
     4bf:	41 f6 c7 01          	test   $0x1,%r15b
     4c3:	0f 84 ae 00 00 00    	je     0x577
     4c9:	49 ff 84 24 e0 00 00 	incq   0xe0(%r12)
     4d0:	00 
     4d1:	80 7c 24 04 00       	cmpb   $0x0,0x4(%rsp)
     4d6:	48 8b 54 24 48       	mov    0x48(%rsp),%rdx
     4db:	4c 8b 7c 24 20       	mov    0x20(%rsp),%r15
     4e0:	4c 8b 74 24 38       	mov    0x38(%rsp),%r14
     4e5:	74 29                	je     0x510
     4e7:	49 ff 84 24 d0 00 00 	incq   0xd0(%r12)
     4ee:	00 
     4ef:	eb 1f                	jmp    0x510
     4f1:	80 7c 24 04 00       	cmpb   $0x0,0x4(%rsp)
     4f6:	74 08                	je     0x500
     4f8:	49 ff 84 24 d0 00 00 	incq   0xd0(%r12)
     4ff:	00 
     500:	f6 44 24 30 01       	testb  $0x1,0x30(%rsp)
     505:	48 8b 54 24 48       	mov    0x48(%rsp),%rdx
     50a:	0f 84 88 00 00 00    	je     0x598
     510:	4c 89 c7             	mov    %r8,%rdi
     513:	48 83 c4 78          	add    $0x78,%rsp
     517:	e9 2d 05 00 00       	jmp    0xa49
     51c:	4c 89 e6             	mov    %r12,%rsi
     51f:	4c 8b 64 24 28       	mov    0x28(%rsp),%r12
     524:	4c 8b 7c 24 20       	mov    0x20(%rsp),%r15
     529:	48 8b 7c 24 08       	mov    0x8(%rsp),%rdi
     52e:	e9 49 fd ff ff       	jmp    0x27c
     533:	41 8b 07             	mov    (%r15),%eax
     536:	85 c0                	test   %eax,%eax
     538:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     53d:	48 8b 7c 24 08       	mov    0x8(%rsp),%rdi
     542:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     547:	78 1f                	js     0x568
     549:	ff c8                	dec    %eax
     54b:	41 89 07             	mov    %eax,(%r15)
     54e:	75 18                	jne    0x568
     550:	4c 89 ff             	mov    %r15,%rdi
     553:	ff 15 c2 06 00 00    	call   *0x6c2(%rip)        # 0xc1b
     559:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     55e:	48 8b 7c 24 08       	mov    0x8(%rsp),%rdi
     563:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     568:	4c 8b 64 24 28       	mov    0x28(%rsp),%r12
     56d:	4c 8b 7c 24 20       	mov    0x20(%rsp),%r15
     572:	e9 05 fd ff ff       	jmp    0x27c
     577:	49 ff 84 24 d8 00 00 	incq   0xd8(%r12)
     57e:	00 
     57f:	80 7c 24 04 00       	cmpb   $0x0,0x4(%rsp)
     584:	4c 8b 7c 24 20       	mov    0x20(%rsp),%r15
     589:	4c 8b 74 24 38       	mov    0x38(%rsp),%r14
     58e:	74 08                	je     0x598
     590:	49 ff 84 24 d0 00 00 	incq   0xd0(%r12)
     597:	00 
     598:	4c 89 c7             	mov    %r8,%rdi
     59b:	31 d2                	xor    %edx,%edx
     59d:	48 83 c4 78          	add    $0x78,%rsp
     5a1:	48 83 ec 18          	sub    $0x18,%rsp
     5a5:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
     5aa:	48 89 74 24 08       	mov    %rsi,0x8(%rsp)
     5af:	48 89 fb             	mov    %rdi,%rbx
     5b2:	48 89 f8             	mov    %rdi,%rax
     5b5:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     5b9:	48 8b 78 10          	mov    0x10(%rax),%rdi
     5bd:	48 8b 48 18          	mov    0x18(%rax),%rcx
     5c1:	48 01 f9             	add    %rdi,%rcx
     5c4:	48 89 48 10          	mov    %rcx,0x10(%rax)
     5c8:	48 ff 48 20          	decq   0x20(%rax)
     5cc:	ff 15 71 06 00 00    	call   *0x671(%rip)        # 0xc43
     5d2:	48 85 c0             	test   %rax,%rax
     5d5:	74 18                	je     0x5ef
     5d7:	0f b7 50 06          	movzwl 0x6(%rax),%edx
     5db:	83 e2 01             	and    $0x1,%edx
     5de:	48 09 c2             	or     %rax,%rdx
     5e1:	48 89 df             	mov    %rbx,%rdi
     5e4:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     5e9:	48 83 c4 18          	add    $0x18,%rsp
     5ed:	eb 21                	jmp    0x610
     5ef:	49 89 1e             	mov    %rbx,(%r14)
     5f2:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     5f7:	49 89 76 08          	mov    %rsi,0x8(%r14)
     5fb:	49 83 c6 10          	add    $0x10,%r14
     5ff:	48 89 df             	mov    %rbx,%rdi
     602:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
     607:	48 83 c4 18          	add    $0x18,%rsp
     60b:	e9 89 04 00 00       	jmp    0xa99
     610:	48 b8 7c 3a 47 88 cd 	movabs $0x7fcd88473a7c,%rax
     617:	7f 00 00 
     61a:	49 89 45 38          	mov    %rax,0x38(%r13)
     61e:	49 8b 45 68          	mov    0x68(%r13),%rax
     622:	49 89 55 68          	mov    %rdx,0x68(%r13)
     626:	48 89 c2             	mov    %rax,%rdx
     629:	49 89 3e             	mov    %rdi,(%r14)
     62c:	49 89 76 08          	mov    %rsi,0x8(%r14)
     630:	49 83 c6 10          	add    $0x10,%r14
     634:	48 89 d7             	mov    %rdx,%rdi
     637:	4d 89 75 40          	mov    %r14,0x40(%r13)
     63b:	40 f6 c7 01          	test   $0x1,%dil
     63f:	75 0f                	jne    0x650
     641:	ff 0f                	decl   (%rdi)
     643:	75 0b                	jne    0x650
     645:	50                   	push   %rax
     646:	ff 15 cf 05 00 00    	call   *0x5cf(%rip)        # 0xc1b
     64c:	48 83 c4 08          	add    $0x8,%rsp
     650:	31 ff                	xor    %edi,%edi
     652:	31 f6                	xor    %esi,%esi
     654:	31 d2                	xor    %edx,%edx
     656:	49 8b 7d 60          	mov    0x60(%r13),%rdi
     65a:	40 f6 c7 01          	test   $0x1,%dil
     65e:	75 02                	jne    0x662
     660:	ff 07                	incl   (%rdi)
     662:	41 80 7c 24 22 00    	cmpb   $0x0,0x22(%r12)
     668:	0f 84 5f 04 00 00    	je     0xacd
     66e:	49 8b 75 68          	mov    0x68(%r13),%rsi
     672:	48 83 ce 01          	or     $0x1,%rsi
     676:	49 8b 55 68          	mov    0x68(%r13),%rdx
     67a:	48 83 ca 01          	or     $0x1,%rdx
     67e:	48 89 d0             	mov    %rdx,%rax
     681:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     685:	48 83 78 10 10       	cmpq   $0x10,0x10(%rax)
     68a:	0f 83 87 04 00 00    	jae    0xb17
     690:	49 89 3e             	mov    %rdi,(%r14)
     693:	49 83 c6 08          	add    $0x8,%r14
     697:	48 89 f7             	mov    %rsi,%rdi
     69a:	48 89 d6             	mov    %rdx,%rsi
     69d:	48 83 ec 18          	sub    $0x18,%rsp
     6a1:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
     6a6:	48 89 fb             	mov    %rdi,%rbx
     6a9:	48 83 e7 fe          	and    $0xfffffffffffffffe,%rdi
     6ad:	48 89 74 24 08       	mov    %rsi,0x8(%rsp)
     6b2:	48 83 e6 fe          	and    $0xfffffffffffffffe,%rsi
     6b6:	ff 15 6f 05 00 00    	call   *0x56f(%rip)        # 0xc2b
     6bc:	48 83 f8 01          	cmp    $0x1,%rax
     6c0:	75 16                	jne    0x6d8
     6c2:	48 89 df             	mov    %rbx,%rdi
     6c5:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     6ca:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
     6cf:	48 83 c4 18          	add    $0x18,%rsp
     6d3:	e9 73 04 00 00       	jmp    0xb4b
     6d8:	48 89 c7             	mov    %rax,%rdi
     6db:	48 89 de             	mov    %rbx,%rsi
     6de:	48 8b 54 24 08       	mov    0x8(%rsp),%rdx
     6e3:	48 83 c4 18          	add    $0x18,%rsp
     6e7:	48 89 f8             	mov    %rdi,%rax
     6ea:	49 8b 7e f8          	mov    -0x8(%r14),%rdi
     6ee:	48 89 f9             	mov    %rdi,%rcx
     6f1:	48 83 e1 fe          	and    $0xfffffffffffffffe,%rcx
     6f5:	49 b8 00 8c 14 68 09 	movabs $0x560968148c00,%r8
     6fc:	56 00 00 
     6ff:	4c 39 41 08          	cmp    %r8,0x8(%rcx)
     703:	75 07                	jne    0x70c
     705:	48 83 79 10 10       	cmpq   $0x10,0x10(%rcx)
     70a:	72 08                	jb     0x714
     70c:	48 89 c7             	mov    %rax,%rdi
     70f:	e9 67 04 00 00       	jmp    0xb7b
     714:	49 83 c6 f8          	add    $0xfffffffffffffff8,%r14
     718:	48 89 c6             	mov    %rax,%rsi
     71b:	48 83 ec 18          	sub    $0x18,%rsp
     71f:	48 89 54 24 08       	mov    %rdx,0x8(%rsp)
     724:	48 89 f3             	mov    %rsi,%rbx
     727:	49 89 f9             	mov    %rdi,%r9
     72a:	48 83 e6 fe          	and    $0xfffffffffffffffe,%rsi
     72e:	48 83 e7 fe          	and    $0xfffffffffffffffe,%rdi
     732:	83 3e 00             	cmpl   $0x0,(%rsi)
     735:	0f 88 89 00 00 00    	js     0x7c4
     73b:	48 8b 47 10          	mov    0x10(%rdi),%rax
     73f:	83 e0 03             	and    $0x3,%eax
     742:	b9 01 00 00 00       	mov    $0x1,%ecx
     747:	ba 01 00 00 00       	mov    $0x1,%edx
     74c:	48 29 c2             	sub    %rax,%rdx
     74f:	44 8b 47 18          	mov    0x18(%rdi),%r8d
     753:	4c 0f af c2          	imul   %rdx,%r8
     757:	48 8b 46 10          	mov    0x10(%rsi),%rax
     75b:	83 e0 03             	and    $0x3,%eax
     75e:	48 29 c1             	sub    %rax,%rcx
     761:	8b 46 18             	mov    0x18(%rsi),%eax
     764:	48 0f af c1          	imul   %rcx,%rax
     768:	4c 01 c0             	add    %r8,%rax
     76b:	48 8d 88 ff fb ff ff 	lea    -0x401(%rax),%rcx
     772:	48 81 f9 fa fb ff ff 	cmp    $0xfffffffffffffbfa,%rcx
     779:	0f 92 c1             	setb   %cl
     77c:	48 8d 90 ff ff ff 3f 	lea    0x3fffffff(%rax),%rdx
     783:	48 81 fa ff ff ff 7f 	cmp    $0x7fffffff,%rdx
     78a:	0f 92 c2             	setb   %dl
     78d:	20 ca                	and    %cl,%dl
     78f:	80 fa 01             	cmp    $0x1,%dl
     792:	75 30                	jne    0x7c4
     794:	48 89 c1             	mov    %rax,%rcx
     797:	48 c1 e9 3f          	shr    $0x3f,%rcx
     79b:	48 8d 0c 4d 08 00 00 	lea    0x8(,%rcx,2),%rcx
     7a2:	00 
     7a3:	48 89 4e 10          	mov    %rcx,0x10(%rsi)
     7a7:	48 89 c1             	mov    %rax,%rcx
     7aa:	48 f7 d9             	neg    %rcx
     7ad:	48 0f 48 c8          	cmovs  %rax,%rcx
     7b1:	89 4e 18             	mov    %ecx,0x18(%rsi)
     7b4:	f6 c3 01             	test   $0x1,%bl
     7b7:	75 02                	jne    0x7bb
     7b9:	ff 03                	incl   (%rbx)
     7bb:	48 89 d8             	mov    %rbx,%rax
     7be:	48 83 fb 01          	cmp    $0x1,%rbx
     7c2:	75 42                	jne    0x806
     7c4:	4c 89 64 24 10       	mov    %r12,0x10(%rsp)
     7c9:	4d 89 ec             	mov    %r13,%r12
     7cc:	4d 89 f5             	mov    %r14,%r13
     7cf:	4d 89 fe             	mov    %r15,%r14
     7d2:	4d 89 cf             	mov    %r9,%r15
     7d5:	ff 15 48 04 00 00    	call   *0x448(%rip)        # 0xc23
     7db:	4d 89 f9             	mov    %r15,%r9
     7de:	4d 89 f7             	mov    %r14,%r15
     7e1:	4d 89 ee             	mov    %r13,%r14
     7e4:	4d 89 e5             	mov    %r12,%r13
     7e7:	4c 8b 64 24 10       	mov    0x10(%rsp),%r12
     7ec:	48 83 f8 01          	cmp    $0x1,%rax
     7f0:	75 14                	jne    0x806
     7f2:	4c 89 cf             	mov    %r9,%rdi
     7f5:	48 89 de             	mov    %rbx,%rsi
     7f8:	48 8b 54 24 08       	mov    0x8(%rsp),%rdx
     7fd:	48 83 c4 18          	add    $0x18,%rsp
     801:	e9 a1 03 00 00       	jmp    0xba7
     806:	48 89 c7             	mov    %rax,%rdi
     809:	4c 89 ce             	mov    %r9,%rsi
     80c:	48 89 da             	mov    %rbx,%rdx
     80f:	48 83 c4 18          	add    $0x18,%rsp
     813:	48 89 d3             	mov    %rdx,%rbx
     816:	f6 c3 01             	test   $0x1,%bl
     819:	75 52                	jne    0x86d
     81b:	ff 0b                	decl   (%rbx)
     81d:	75 4e                	jne    0x86d
     81f:	48 83 ec 18          	sub    $0x18,%rsp
     823:	48 89 7c 24 08       	mov    %rdi,0x8(%rsp)
     828:	48 89 74 24 10       	mov    %rsi,0x10(%rsp)
     82d:	48 b8 30 f2 17 68 09 	movabs $0x56096817f230,%rax
     834:	56 00 00 
     837:	48 8b 00             	mov    (%rax),%rax
     83a:	48 85 c0             	test   %rax,%rax
     83d:	74 17                	je     0x856
     83f:	48 b9 38 f2 17 68 09 	movabs $0x56096817f238,%rcx
     846:	56 00 00 
     849:	48 8b 11             	mov    (%rcx),%rdx
     84c:	48 89 df             	mov    %rbx,%rdi
     84f:	be 01 00 00 00       	mov    $0x1,%esi
     854:	ff d0                	call   *%rax
     856:	48 89 df             	mov    %rbx,%rdi
     859:	ff 15 ec 03 00 00    	call   *0x3ec(%rip)        # 0xc4b
     85f:	48 8b 74 24 10       	mov    0x10(%rsp),%rsi
     864:	48 8b 7c 24 08       	mov    0x8(%rsp),%rdi
     869:	48 83 c4 18          	add    $0x18,%rsp
     86d:	48 89 da             	mov    %rbx,%rdx
     870:	48 89 f3             	mov    %rsi,%rbx
     873:	f6 c3 01             	test   $0x1,%bl
     876:	75 52                	jne    0x8ca
     878:	ff 0b                	decl   (%rbx)
     87a:	75 4e                	jne    0x8ca
     87c:	48 83 ec 18          	sub    $0x18,%rsp
     880:	48 89 7c 24 08       	mov    %rdi,0x8(%rsp)
     885:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
     88a:	48 b8 30 f2 17 68 09 	movabs $0x56096817f230,%rax
     891:	56 00 00 
     894:	48 8b 00             	mov    (%rax),%rax
     897:	48 85 c0             	test   %rax,%rax
     89a:	74 17                	je     0x8b3
     89c:	48 b9 38 f2 17 68 09 	movabs $0x56096817f238,%rcx
     8a3:	56 00 00 
     8a6:	48 8b 11             	mov    (%rcx),%rdx
     8a9:	48 89 df             	mov    %rbx,%rdi
     8ac:	be 01 00 00 00       	mov    $0x1,%esi
     8b1:	ff d0                	call   *%rax
     8b3:	48 89 df             	mov    %rbx,%rdi
     8b6:	ff 15 8f 03 00 00    	call   *0x38f(%rip)        # 0xc4b
     8bc:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
     8c1:	48 8b 7c 24 08       	mov    0x8(%rsp),%rdi
     8c6:	48 83 c4 18          	add    $0x18,%rsp
     8ca:	48 89 de             	mov    %rbx,%rsi
     8cd:	49 8b 45 60          	mov    0x60(%r13),%rax
     8d1:	49 89 7d 60          	mov    %rdi,0x60(%r13)
     8d5:	48 89 c7             	mov    %rax,%rdi
     8d8:	48 89 fb             	mov    %rdi,%rbx
     8db:	f6 c3 01             	test   $0x1,%bl
     8de:	75 52                	jne    0x932
     8e0:	ff 0b                	decl   (%rbx)
     8e2:	75 4e                	jne    0x932
     8e4:	48 83 ec 18          	sub    $0x18,%rsp
     8e8:	48 89 74 24 08       	mov    %rsi,0x8(%rsp)
     8ed:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
     8f2:	48 b8 30 f2 17 68 09 	movabs $0x56096817f230,%rax
     8f9:	56 00 00 
     8fc:	48 8b 00             	mov    (%rax),%rax
     8ff:	48 85 c0             	test   %rax,%rax
     902:	74 17                	je     0x91b
     904:	48 b9 38 f2 17 68 09 	movabs $0x56096817f238,%rcx
     90b:	56 00 00 
     90e:	48 8b 11             	mov    (%rcx),%rdx
     911:	48 89 df             	mov    %rbx,%rdi
     914:	be 01 00 00 00       	mov    $0x1,%esi
     919:	ff d0                	call   *%rax
     91b:	48 89 df             	mov    %rbx,%rdi
     91e:	ff 15 27 03 00 00    	call   *0x327(%rip)        # 0xc4b
     924:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
     929:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     92e:	48 83 c4 18          	add    $0x18,%rsp
     932:	48 89 df             	mov    %rbx,%rdi
     935:	e9 12 f7 ff ff       	jmp    0x4c
     93a:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     941:	00 00 00 00 
     945:	4d 89 75 40          	mov    %r14,0x40(%r13)
     949:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     94e:	75 0e                	jne    0x95e
     950:	48 b8 c0 b9 15 68 09 	movabs $0x56096815b9c0,%rax
     957:	56 00 00 
     95a:	48 8b 00             	mov    (%rax),%rax
     95d:	c3                   	ret
     95e:	49 8b 45 00          	mov    0x0(%r13),%rax
     962:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     966:	48 b9 21 00 00 00 00 	movabs $0x21,%rcx
     96d:	00 00 00 
     970:	89 c9                	mov    %ecx,%ecx
     972:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     976:	48 05 c8 00 00 00    	add    $0xc8,%rax
     97c:	c3                   	ret
     97d:	49 8b 45 00          	mov    0x0(%r13),%rax
     981:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     985:	48 b9 21 00 00 00 00 	movabs $0x21,%rcx
     98c:	00 00 00 
     98f:	89 c9                	mov    %ecx,%ecx
     991:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     995:	48 05 c8 00 00 00    	add    $0xc8,%rax
     99b:	49 89 45 38          	mov    %rax,0x38(%r13)
     99f:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     9a6:	00 00 00 00 
     9aa:	4d 89 75 40          	mov    %r14,0x40(%r13)
     9ae:	31 c0                	xor    %eax,%eax
     9b0:	c3                   	ret
     9b1:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     9b8:	00 00 00 00 
     9bc:	4d 89 75 40          	mov    %r14,0x40(%r13)
     9c0:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     9c5:	75 0e                	jne    0x9d5
     9c7:	48 b8 c0 b9 15 68 09 	movabs $0x56096815b9c0,%rax
     9ce:	56 00 00 
     9d1:	48 8b 00             	mov    (%rax),%rax
     9d4:	c3                   	ret
     9d5:	49 8b 45 00          	mov    0x0(%r13),%rax
     9d9:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     9dd:	48 b9 10 00 00 00 00 	movabs $0x10,%rcx
     9e4:	00 00 00 
     9e7:	89 c9                	mov    %ecx,%ecx
     9e9:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     9ed:	48 05 c8 00 00 00    	add    $0xc8,%rax
     9f3:	c3                   	ret
     9f4:	48 b8 18 31 82 8b 09 	movabs $0x56098b823118,%rax
     9fb:	56 00 00 
     9fe:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     a05:	48 b8 20 31 82 8b 09 	movabs $0x56098b823120,%rax
     a0c:	56 00 00 
     a0f:	4c 8b 20             	mov    (%rax),%r12
     a12:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     a17:	ff e0                	jmp    *%rax
     a19:	48 b8 28 31 82 8b 09 	movabs $0x56098b823128,%rax
     a20:	56 00 00 
     a23:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     a2a:	49 89 3e             	mov    %rdi,(%r14)
     a2d:	49 89 76 08          	mov    %rsi,0x8(%r14)
     a31:	49 83 c6 10          	add    $0x10,%r14
     a35:	48 b8 30 31 82 8b 09 	movabs $0x56098b823130,%rax
     a3c:	56 00 00 
     a3f:	4c 8b 20             	mov    (%rax),%r12
     a42:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     a47:	ff e0                	jmp    *%rax
     a49:	50                   	push   %rax
     a4a:	49 89 3e             	mov    %rdi,(%r14)
     a4d:	49 89 76 08          	mov    %rsi,0x8(%r14)
     a51:	49 83 c6 10          	add    $0x10,%r14
     a55:	4d 89 75 40          	mov    %r14,0x40(%r13)
     a59:	4c 89 ff             	mov    %r15,%rdi
     a5c:	ff 15 d1 01 00 00    	call   *0x1d1(%rip)        # 0xc33
     a62:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     a69:	00 00 00 00 
     a6d:	4d 89 75 40          	mov    %r14,0x40(%r13)
     a71:	85 c0                	test   %eax,%eax
     a73:	74 04                	je     0xa79
     a75:	31 c0                	xor    %eax,%eax
     a77:	eb 1e                	jmp    0xa97
     a79:	49 8b 45 00          	mov    0x0(%r13),%rax
     a7d:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     a81:	48 b9 21 00 00 00 00 	movabs $0x21,%rcx
     a88:	00 00 00 
     a8b:	89 c9                	mov    %ecx,%ecx
     a8d:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     a91:	48 05 c8 00 00 00    	add    $0xc8,%rax
     a97:	59                   	pop    %rcx
     a98:	c3                   	ret
     a99:	49 8b 45 00          	mov    0x0(%r13),%rax
     a9d:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     aa1:	48 b9 10 00 00 00 00 	movabs $0x10,%rcx
     aa8:	00 00 00 
     aab:	89 c9                	mov    %ecx,%ecx
     aad:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     ab1:	48 05 c8 00 00 00    	add    $0xc8,%rax
     ab7:	49 89 45 38          	mov    %rax,0x38(%r13)
     abb:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     ac2:	00 00 00 00 
     ac6:	4d 89 75 40          	mov    %r14,0x40(%r13)
     aca:	31 c0                	xor    %eax,%eax
     acc:	c3                   	ret
     acd:	49 89 3e             	mov    %rdi,(%r14)
     ad0:	49 83 c6 08          	add    $0x8,%r14
     ad4:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     adb:	00 00 00 00 
     adf:	4d 89 75 40          	mov    %r14,0x40(%r13)
     ae3:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     ae8:	75 0e                	jne    0xaf8
     aea:	48 b8 c0 b9 15 68 09 	movabs $0x56096815b9c0,%rax
     af1:	56 00 00 
     af4:	48 8b 00             	mov    (%rax),%rax
     af7:	c3                   	ret
     af8:	49 8b 45 00          	mov    0x0(%r13),%rax
     afc:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     b00:	48 b9 13 00 00 00 00 	movabs $0x13,%rcx
     b07:	00 00 00 
     b0a:	89 c9                	mov    %ecx,%ecx
     b0c:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     b10:	48 05 c8 00 00 00    	add    $0xc8,%rax
     b16:	c3                   	ret
     b17:	48 b8 38 31 82 8b 09 	movabs $0x56098b823138,%rax
     b1e:	56 00 00 
     b21:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     b28:	49 89 3e             	mov    %rdi,(%r14)
     b2b:	49 89 76 08          	mov    %rsi,0x8(%r14)
     b2f:	49 89 56 10          	mov    %rdx,0x10(%r14)
     b33:	49 83 c6 18          	add    $0x18,%r14
     b37:	48 b8 40 31 82 8b 09 	movabs $0x56098b823140,%rax
     b3e:	56 00 00 
     b41:	4c 8b 20             	mov    (%rax),%r12
     b44:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     b49:	ff e0                	jmp    *%rax
     b4b:	48 b8 48 31 82 8b 09 	movabs $0x56098b823148,%rax
     b52:	56 00 00 
     b55:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     b5c:	49 89 3e             	mov    %rdi,(%r14)
     b5f:	49 89 76 08          	mov    %rsi,0x8(%r14)
     b63:	49 83 c6 10          	add    $0x10,%r14
     b67:	48 b8 50 31 82 8b 09 	movabs $0x56098b823150,%rax
     b6e:	56 00 00 
     b71:	4c 8b 20             	mov    (%rax),%r12
     b74:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     b79:	ff e0                	jmp    *%rax
     b7b:	48 b8 58 31 82 8b 09 	movabs $0x56098b823158,%rax
     b82:	56 00 00 
     b85:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     b8c:	49 89 3e             	mov    %rdi,(%r14)
     b8f:	49 83 c6 08          	add    $0x8,%r14
     b93:	48 b8 60 31 82 8b 09 	movabs $0x56098b823160,%rax
     b9a:	56 00 00 
     b9d:	4c 8b 20             	mov    (%rax),%r12
     ba0:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     ba5:	ff e0                	jmp    *%rax
     ba7:	48 b8 68 31 82 8b 09 	movabs $0x56098b823168,%rax
     bae:	56 00 00 
     bb1:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     bb8:	49 89 3e             	mov    %rdi,(%r14)
     bbb:	49 89 76 08          	mov    %rsi,0x8(%r14)
     bbf:	49 83 c6 10          	add    $0x10,%r14
     bc3:	48 b8 70 31 82 8b 09 	movabs $0x56098b823170,%rax
     bca:	56 00 00 
     bcd:	4c 8b 20             	mov    (%rax),%r12
     bd0:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     bd5:	ff e0                	jmp    *%rax
     bd7:	50                   	push   %rax
     bd8:	48 bf f3 cb 28 88 cd 	movabs $0x7fcd8828cbf3,%rdi
     bdf:	7f 00 00 
     be2:	48 be fe cb 28 88 cd 	movabs $0x7fcd8828cbfe,%rsi
     be9:	7f 00 00 
     bec:	ff 15 49 00 00 00    	call   *0x49(%rip)        # 0xc3b
     bf2:	00 5f 4a             	add    %bl,0x4a(%rdi)
     bf5:	49 54                	rex.WB push %r12
     bf7:	5f                   	pop    %rdi
     bf8:	45                   	rex.RB
     bf9:	4e 54                	rex.WRX push %rsp
     bfb:	52                   	push   %rdx
     bfc:	59                   	pop    %rcx
     bfd:	00 46 61             	add    %al,0x61(%rsi)
     c00:	74 61                	je     0xc63
     c02:	6c                   	insb   (%dx),%es:(%rdi)
     c03:	20 65 72             	and    %ah,0x72(%rbp)
     c06:	72 6f                	jb     0xc77
     c08:	72 20                	jb     0xc2a
     c0a:	75 6f                	jne    0xc7b
     c0c:	70 20                	jo     0xc2e
     c0e:	65 78 65             	gs js  0xc76
     c11:	63 75 74             	movsxd 0x74(%rbp),%esi
     c14:	65 64 2e 00 00       	gs fs add %al,%fs:(%rax)
     c19:	00 00                	add    %al,(%rax)
     c1b:	e0 40                	loopne 0xc5d
     c1d:	c7                   	(bad)
     c1e:	67 09 56 00          	or     %edx,0x0(%esi)
     c22:	00 80 da c4 67 09    	add    %al,0x967c4da(%rax)
     c28:	56                   	push   %rsi
     c29:	00 00                	add    %al,(%rax)
     c2b:	00 dd                	add    %bl,%ch
     c2d:	c4 67 09 56          	(bad)
     c31:	00 00                	add    %al,(%rax)
     c33:	e0 2b                	loopne 0xc60
     c35:	dc 67 09             	fsubl  0x9(%rdi)
     c38:	56                   	push   %rsi
     c39:	00 00                	add    %al,(%rax)
     c3b:	90                   	nop
     c3c:	0c e4                	or     $0xe4,%al
     c3e:	67 09 56 00          	or     %edx,0x0(%esi)
     c42:	00 d0                	add    %dl,%al
     c44:	4b c4 67 09 56       	(bad)
     c49:	00 00                	add    %al,(%rax)
     c4b:	80 8a c3 67 09 56 00 	orb    $0x0,0x560967c3(%rdx)
     c52:	00 30                	add    %dh,(%rax)
     c54:	0f e2 67 09          	psrad  0x9(%rdi),%mm4
     c58:	56                   	push   %rsi
     c59:	00 00                	add    %al,(%rax)
     c5b:	60                   	(bad)
     c5c:	ab                   	stos   %eax,%es:(%rdi)
     c5d:	c4 67 09 56          	(bad)
     c61:	00 00                	add    %al,(%rax)
     c63:	50                   	push   %rax
     c64:	c1 b8 67 09 56 00 00 	sarl   $0x0,0x560967(%rax)
     c6b:	f0 a5                	lock movsl %ds:(%rsi),%es:(%rdi)
     c6d:	c4 67 09 56          	(bad)
	...
