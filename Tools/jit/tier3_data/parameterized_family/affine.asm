
Tools/jit/tier3_data/parameterized_family/affine.bin:     file format binary


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
      30:	ff 15 b7 0d 00 00    	call   *0xdb7(%rip)        # 0xded
      36:	48 89 df             	mov    %rbx,%rdi
      39:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
      3e:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
      43:	48 83 c4 18          	add    $0x18,%rsp
      47:	e9 09 0a 00 00       	jmp    0xa55
      4c:	41 c6 44 24 24 00    	movb   $0x0,0x24(%r12)
      52:	48 b8 5a f4 db 16 22 	movabs $0x7f2216dbf45a,%rax
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
      83:	ff 15 44 0d 00 00    	call   *0xd44(%rip)        # 0xdcd
      89:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
      8e:	4c 89 e2             	mov    %r12,%rdx
      91:	4c 8b 64 24 08       	mov    0x8(%rsp),%r12
      96:	85 c0                	test   %eax,%eax
      98:	48 8d 64 24 18       	lea    0x18(%rsp),%rsp
      9d:	74 08                	je     0xa7
      9f:	48 89 de             	mov    %rbx,%rsi
      a2:	e9 f1 09 00 00       	jmp    0xa98
      a7:	31 ff                	xor    %edi,%edi
      a9:	31 f6                	xor    %esi,%esi
      ab:	31 d2                	xor    %edx,%edx
      ad:	41 80 7c 24 22 00    	cmpb   $0x0,0x22(%r12)
      b3:	0f 84 13 0a 00 00    	je     0xacc
      b9:	49 8b 46 f0          	mov    -0x10(%r14),%rax
      bd:	48 89 c1             	mov    %rax,%rcx
      c0:	48 83 e1 fe          	and    $0xfffffffffffffffe,%rcx
      c4:	49 b8 20 2c 32 0e 8c 	movabs $0x558c0e322c20,%r8
      cb:	55 00 00
      ce:	4c 39 41 08          	cmp    %r8,0x8(%rcx)
      d2:	0f 85 37 0a 00 00    	jne    0xb0f
      d8:	49 8b 76 f8          	mov    -0x8(%r14),%rsi
      dc:	49 83 c6 f0          	add    $0xfffffffffffffff0,%r14
      e0:	48 89 c7             	mov    %rax,%rdi
      e3:	48 89 f8             	mov    %rdi,%rax
      e6:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
      ea:	48 83 78 20 00       	cmpq   $0x0,0x20(%rax)
      ef:	0f 8e 3f 0a 00 00    	jle    0xb34
      f5:	48 81 ec 88 00 00 00 	sub    $0x88,%rsp
      fc:	49 89 f8             	mov    %rdi,%r8
      ff:	4d 89 f9             	mov    %r15,%r9
     102:	4d 89 e2             	mov    %r12,%r10
     105:	48 b8 45 00 00 00 00 	movabs $0x45,%rax
     10c:	00 00 00
     10f:	44 0f b7 d8          	movzwl %ax,%r11d
     113:	41 c1 eb 04          	shr    $0x4,%r11d
     117:	49 bc 32 00 00 00 00 	movabs $0x32,%r12
     11e:	00 00 00
     121:	4b 8b 7c dd 50       	mov    0x50(%r13,%r11,8),%rdi
     126:	41 0f ba e4 08       	bt     $0x8,%r12d
     12b:	c7 44 24 3c 00 00 00 	movl   $0x0,0x3c(%rsp)
     132:	00
     133:	73 05                	jae    0x13a
     135:	45 31 ff             	xor    %r15d,%r15d
     138:	eb 16                	jmp    0x150
     13a:	48 b8 32 00 00 00 00 	movabs $0x32,%rax
     141:	00 00 00
     144:	83 e0 0f             	and    $0xf,%eax
     147:	4d 8b 7c c5 50       	mov    0x50(%r13,%rax,8),%r15
     14c:	49 83 e7 fe          	and    $0xfffffffffffffffe,%r15
     150:	4c 89 c1             	mov    %r8,%rcx
     153:	48 83 e1 fe          	and    $0xfffffffffffffffe,%rcx
     157:	48 b8 32 00 00 00 00 	movabs $0x32,%rax
     15e:	00 00 00
     161:	0f ba e0 09          	bt     $0x9,%eax
     165:	73 04                	jae    0x16b
     167:	31 db                	xor    %ebx,%ebx
     169:	eb 14                	jmp    0x17f
     16b:	44 89 e0             	mov    %r12d,%eax
     16e:	c1 e8 04             	shr    $0x4,%eax
     171:	83 e0 0f             	and    $0xf,%eax
     174:	89 c0                	mov    %eax,%eax
     176:	49 8b 5c c5 50       	mov    0x50(%r13,%rax,8),%rbx
     17b:	48 83 e3 fe          	and    $0xfffffffffffffffe,%rbx
     17f:	48 b8 20 2c 32 0e 8c 	movabs $0x558c0e322c20,%rax
     186:	55 00 00
     189:	48 39 41 08          	cmp    %rax,0x8(%rcx)
     18d:	75 14                	jne    0x1a3
     18f:	48 83 e7 fe          	and    $0xfffffffffffffffe,%rdi
     193:	48 b8 00 bc 31 0e 8c 	movabs $0x558c0e31bc00,%rax
     19a:	55 00 00
     19d:	48 39 47 08          	cmp    %rax,0x8(%rdi)
     1a1:	74 17                	je     0x1ba
     1a3:	4d 89 d4             	mov    %r10,%r12
     1a6:	4d 89 cf             	mov    %r9,%r15
     1a9:	4c 89 c7             	mov    %r8,%rdi
     1ac:	31 d2                	xor    %edx,%edx
     1ae:	48 81 c4 88 00 00 00 	add    $0x88,%rsp
     1b5:	e9 5e 04 00 00       	jmp    0x618
     1ba:	48 89 4c 24 70       	mov    %rcx,0x70(%rsp)
     1bf:	48 b9 32 00 00 00 00 	movabs $0x32,%rcx
     1c6:	00 00 00
     1c9:	0f ba e1 08          	bt     $0x8,%ecx
     1cd:	72 06                	jb     0x1d5
     1cf:	49 39 47 08          	cmp    %rax,0x8(%r15)
     1d3:	75 ce                	jne    0x1a3
     1d5:	0f ba e1 09          	bt     $0x9,%ecx
     1d9:	72 06                	jb     0x1e1
     1db:	48 39 43 08          	cmp    %rax,0x8(%rbx)
     1df:	75 c2                	jne    0x1a3
     1e1:	4c 89 9c 24 80 00 00 	mov    %r11,0x80(%rsp)
     1e8:	00
     1e9:	4c 89 54 24 30       	mov    %r10,0x30(%rsp)
     1ee:	48 89 54 24 58       	mov    %rdx,0x58(%rsp)
     1f3:	4c 89 4c 24 18       	mov    %r9,0x18(%rsp)
     1f8:	48 b8 32 00 00 00 00 	movabs $0x32,%rax
     1ff:	00 00 00
     202:	c1 e8 08             	shr    $0x8,%eax
     205:	83 e0 01             	and    $0x1,%eax
     208:	48 89 44 24 20       	mov    %rax,0x20(%rsp)
     20d:	4c 89 44 24 28       	mov    %r8,0x28(%rsp)
     212:	4d 89 06             	mov    %r8,(%r14)
     215:	48 89 74 24 60       	mov    %rsi,0x60(%rsp)
     21a:	49 89 76 08          	mov    %rsi,0x8(%r14)
     21e:	4c 89 74 24 40       	mov    %r14,0x40(%rsp)
     223:	49 83 c6 10          	add    $0x10,%r14
     227:	4c 89 6c 24 10       	mov    %r13,0x10(%rsp)
     22c:	4d 89 75 40          	mov    %r14,0x40(%r13)
     230:	4c 8d 6c 24 3c       	lea    0x3c(%rsp),%r13
     235:	4c 89 ee             	mov    %r13,%rsi
     238:	ff 15 b7 0b 00 00    	call   *0xbb7(%rip)        # 0xdf5
     23e:	48 89 44 24 48       	mov    %rax,0x48(%rsp)
     243:	41 8b 45 00          	mov    0x0(%r13),%eax
     247:	85 c0                	test   %eax,%eax
     249:	0f 95 c1             	setne  %cl
     24c:	0a 4c 24 20          	or     0x20(%rsp),%cl
     250:	74 0d                	je     0x25f
     252:	4d 89 e7             	mov    %r12,%r15
     255:	49 c1 e7 18          	shl    $0x18,%r15
     259:	49 c1 ff 28          	sar    $0x28,%r15
     25d:	eb 18                	jmp    0x277
     25f:	4c 8d 6c 24 3c       	lea    0x3c(%rsp),%r13
     264:	4c 89 ff             	mov    %r15,%rdi
     267:	4c 89 ee             	mov    %r13,%rsi
     26a:	ff 15 85 0b 00 00    	call   *0xb85(%rip)        # 0xdf5
     270:	49 89 c7             	mov    %rax,%r15
     273:	41 8b 45 00          	mov    0x0(%r13),%eax
     277:	49 c1 fc 28          	sar    $0x28,%r12
     27b:	48 b9 32 00 00 00 00 	movabs $0x32,%rcx
     282:	00 00 00
     285:	0f ba e1 09          	bt     $0x9,%ecx
     289:	72 15                	jb     0x2a0
     28b:	85 c0                	test   %eax,%eax
     28d:	75 11                	jne    0x2a0
     28f:	48 8d 74 24 3c       	lea    0x3c(%rsp),%rsi
     294:	48 89 df             	mov    %rbx,%rdi
     297:	ff 15 58 0b 00 00    	call   *0xb58(%rip)        # 0xdf5
     29d:	49 89 c4             	mov    %rax,%r12
     2a0:	ff 15 57 0b 00 00    	call   *0xb57(%rip)        # 0xdfd
     2a6:	48 85 c0             	test   %rax,%rax
     2a9:	74 2a                	je     0x2d5
     2ab:	4c 8b 64 24 30       	mov    0x30(%rsp),%r12
     2b0:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     2b5:	4c 8b 7c 24 18       	mov    0x18(%rsp),%r15
     2ba:	48 8b 7c 24 28       	mov    0x28(%rsp),%rdi
     2bf:	48 8b 74 24 60       	mov    0x60(%rsp),%rsi
     2c4:	48 8b 54 24 58       	mov    0x58(%rsp),%rdx
     2c9:	48 81 c4 88 00 00 00 	add    $0x88,%rsp
     2d0:	e9 df 08 00 00       	jmp    0xbb4
     2d5:	4c 89 74 24 78       	mov    %r14,0x78(%rsp)
     2da:	83 7c 24 3c 00       	cmpl   $0x0,0x3c(%rsp)
     2df:	48 8b 74 24 60       	mov    0x60(%rsp),%rsi
     2e4:	4c 8b 44 24 28       	mov    0x28(%rsp),%r8
     2e9:	4c 8b 4c 24 18       	mov    0x18(%rsp),%r9
     2ee:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     2f3:	4c 8b 54 24 30       	mov    0x30(%rsp),%r10
     2f8:	4c 8b 74 24 40       	mov    0x40(%rsp),%r14
     2fd:	48 8b 4c 24 70       	mov    0x70(%rsp),%rcx
     302:	0f 85 9b fe ff ff    	jne    0x1a3
     308:	48 8b 51 20          	mov    0x20(%rcx),%rdx
     30c:	48 83 fa 02          	cmp    $0x2,%rdx
     310:	0f 8c 8d fe ff ff    	jl     0x1a3
     316:	4c 89 7c 24 50       	mov    %r15,0x50(%rsp)
     31b:	49 8b 45 00          	mov    0x0(%r13),%rax
     31f:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     323:	4c 8b 98 a8 00 00 00 	mov    0xa8(%rax),%r11
     32a:	4c 8b 79 10          	mov    0x10(%rcx),%r15
     32e:	41 8a 7a 22          	mov    0x22(%r10),%dil
     332:	40 84 ff             	test   %dil,%dil
     335:	0f 94 c3             	sete   %bl
     338:	49 8b 41 18          	mov    0x18(%r9),%rax
     33c:	4c 39 d8             	cmp    %r11,%rax
     33f:	0f 95 c0             	setne  %al
     342:	89 c1                	mov    %eax,%ecx
     344:	89 5c 24 6c          	mov    %ebx,0x6c(%rsp)
     348:	08 d8                	or     %bl,%al
     34a:	a8 01                	test   $0x1,%al
     34c:	74 23                	je     0x371
     34e:	b8 01 00 00 00       	mov    $0x1,%eax
     353:	31 db                	xor    %ebx,%ebx
     355:	48 c7 44 24 20 00 00 	movq   $0x0,0x20(%rsp)
     35c:	00 00
     35e:	c7 44 24 0c 00 00 00 	movl   $0x0,0xc(%rsp)
     365:	00
     366:	89 ca                	mov    %ecx,%edx
     368:	8b 4c 24 6c          	mov    0x6c(%rsp),%ecx
     36c:	e9 f0 00 00 00       	jmp    0x461
     371:	4c 8d 42 ff          	lea    -0x1(%rdx),%r8
     375:	48 83 c2 fe          	add    $0xfffffffffffffffe,%rdx
     379:	b8 01 00 00 00       	mov    $0x1,%eax
     37e:	31 db                	xor    %ebx,%ebx
     380:	45 31 d2             	xor    %r10d,%r10d
     383:	4c 8b 4c 24 48       	mov    0x48(%rsp),%r9
     388:	4c 8b 74 24 50       	mov    0x50(%rsp),%r14
     38d:	4d 0f af f7          	imul   %r15,%r14
     391:	0f 80 86 00 00 00    	jo     0x41d
     397:	4c 89 7c 24 20       	mov    %r15,0x20(%rsp)
     39c:	4d 01 e6             	add    %r12,%r14
     39f:	70 6d                	jo     0x40e
     3a1:	4d 01 ce             	add    %r9,%r14
     3a4:	70 68                	jo     0x40e
     3a6:	4c 8b 4c 24 70       	mov    0x70(%rsp),%r9
     3ab:	4d 8b 79 18          	mov    0x18(%r9),%r15
     3af:	4c 8b 54 24 20       	mov    0x20(%rsp),%r10
     3b4:	4d 01 d7             	add    %r10,%r15
     3b7:	48 39 da             	cmp    %rbx,%rdx
     3ba:	74 75                	je     0x431
     3bc:	4c 8b 4c 24 18       	mov    0x18(%rsp),%r9
     3c1:	4d 8b 49 18          	mov    0x18(%r9),%r9
     3c5:	48 ff c3             	inc    %rbx
     3c8:	4d 39 d9             	cmp    %r11,%r9
     3cb:	41 0f 95 c5          	setne  %r13b
     3cf:	75 0b                	jne    0x3dc
     3d1:	48 ff c0             	inc    %rax
     3d4:	4d 89 f1             	mov    %r14,%r9
     3d7:	40 84 ff             	test   %dil,%dil
     3da:	75 ac                	jne    0x388
     3dc:	4c 89 74 24 48       	mov    %r14,0x48(%rsp)
     3e1:	48 8d 43 01          	lea    0x1(%rbx),%rax
     3e5:	c7 44 24 0c 00 00 00 	movl   $0x0,0xc(%rsp)
     3ec:	00
     3ed:	4c 8b 44 24 28       	mov    0x28(%rsp),%r8
     3f2:	4c 8b 4c 24 18       	mov    0x18(%rsp),%r9
     3f7:	44 89 ea             	mov    %r13d,%edx
     3fa:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     3ff:	4c 8b 54 24 30       	mov    0x30(%rsp),%r10
     404:	4c 8b 74 24 40       	mov    0x40(%rsp),%r14
     409:	e9 5a ff ff ff       	jmp    0x368
     40e:	b1 01                	mov    $0x1,%cl
     410:	89 4c 24 0c          	mov    %ecx,0xc(%rsp)
     414:	31 d2                	xor    %edx,%edx
     416:	4c 8b 7c 24 20       	mov    0x20(%rsp),%r15
     41b:	eb 08                	jmp    0x425
     41d:	b1 01                	mov    $0x1,%cl
     41f:	89 4c 24 0c          	mov    %ecx,0xc(%rsp)
     423:	31 d2                	xor    %edx,%edx
     425:	4c 89 54 24 20       	mov    %r10,0x20(%rsp)
     42a:	4c 89 4c 24 48       	mov    %r9,0x48(%rsp)
     42f:	eb 15                	jmp    0x446
     431:	4c 89 74 24 48       	mov    %r14,0x48(%rsp)
     436:	c7 44 24 0c 00 00 00 	movl   $0x0,0xc(%rsp)
     43d:	00
     43e:	4c 89 c0             	mov    %r8,%rax
     441:	4c 89 c3             	mov    %r8,%rbx
     444:	31 d2                	xor    %edx,%edx
     446:	31 c9                	xor    %ecx,%ecx
     448:	4c 8b 44 24 28       	mov    0x28(%rsp),%r8
     44d:	4c 8b 4c 24 18       	mov    0x18(%rsp),%r9
     452:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     457:	4c 8b 54 24 30       	mov    0x30(%rsp),%r10
     45c:	4c 8b 74 24 40       	mov    0x40(%rsp),%r14
     461:	08 ca                	or     %cl,%dl
     463:	49 01 82 c0 00 00 00 	add    %rax,0xc0(%r10)
     46a:	89 54 24 50          	mov    %edx,0x50(%rsp)
     46e:	f6 c2 01             	test   $0x1,%dl
     471:	74 07                	je     0x47a
     473:	49 ff 82 c8 00 00 00 	incq   0xc8(%r10)
     47a:	48 85 db             	test   %rbx,%rbx
     47d:	0f 84 0a 01 00 00    	je     0x58d
     483:	4d 89 06             	mov    %r8,(%r14)
     486:	49 89 76 08          	mov    %rsi,0x8(%r14)
     48a:	4c 8b 74 24 78       	mov    0x78(%rsp),%r14
     48f:	4d 89 75 40          	mov    %r14,0x40(%r13)
     493:	48 8b 7c 24 48       	mov    0x48(%rsp),%rdi
     498:	ff 15 67 09 00 00    	call   *0x967(%rip)        # 0xe05
     49e:	48 85 c0             	test   %rax,%rax
     4a1:	0f 84 04 fe ff ff    	je     0x2ab
     4a7:	49 89 c4             	mov    %rax,%r12
     4aa:	48 8b 7c 24 20       	mov    0x20(%rsp),%rdi
     4af:	ff 15 28 09 00 00    	call   *0x928(%rip)        # 0xddd
     4b5:	48 85 c0             	test   %rax,%rax
     4b8:	0f 84 02 01 00 00    	je     0x5c0
     4be:	48 b9 45 00 00 00 00 	movabs $0x45,%rcx
     4c5:	00 00 00
     4c8:	83 e1 0f             	and    $0xf,%ecx
     4cb:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     4d0:	48 8b b4 24 80 00 00 	mov    0x80(%rsp),%rsi
     4d7:	00
     4d8:	49 8b 7c f5 50       	mov    0x50(%r13,%rsi,8),%rdi
     4dd:	89 c9                	mov    %ecx,%ecx
     4df:	4d 8b 74 cd 50       	mov    0x50(%r13,%rcx,8),%r14
     4e4:	41 0f b7 54 24 06    	movzwl 0x6(%r12),%edx
     4ea:	83 e2 01             	and    $0x1,%edx
     4ed:	4c 09 e2             	or     %r12,%rdx
     4f0:	49 89 54 f5 50       	mov    %rdx,0x50(%r13,%rsi,8)
     4f5:	0f b7 50 06          	movzwl 0x6(%rax),%edx
     4f9:	83 e2 01             	and    $0x1,%edx
     4fc:	48 09 c2             	or     %rax,%rdx
     4ff:	49 89 54 cd 50       	mov    %rdx,0x50(%r13,%rcx,8)
     504:	48 8b 44 24 70       	mov    0x70(%rsp),%rax
     509:	4c 89 78 10          	mov    %r15,0x10(%rax)
     50d:	48 29 58 20          	sub    %rbx,0x20(%rax)
     511:	40 f6 c7 01          	test   $0x1,%dil
     515:	75 0f                	jne    0x526
     517:	ff 0f                	decl   (%rdi)
     519:	75 0b                	jne    0x526
     51b:	ff 15 94 08 00 00    	call   *0x894(%rip)        # 0xdb5
     521:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     526:	41 f6 c6 01          	test   $0x1,%r14b
     52a:	75 13                	jne    0x53f
     52c:	41 ff 0e             	decl   (%r14)
     52f:	75 0e                	jne    0x53f
     531:	4c 89 f7             	mov    %r14,%rdi
     534:	ff 15 7b 08 00 00    	call   *0x87b(%rip)        # 0xdb5
     53a:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     53f:	4c 8b 54 24 30       	mov    0x30(%rsp),%r10
     544:	49 ff 82 b0 00 00 00 	incq   0xb0(%r10)
     54b:	49 01 9a b8 00 00 00 	add    %rbx,0xb8(%r10)
     552:	f6 44 24 50 01       	testb  $0x1,0x50(%rsp)
     557:	0f 84 89 00 00 00    	je     0x5e6
     55d:	49 ff 82 e0 00 00 00 	incq   0xe0(%r10)
     564:	80 7c 24 0c 00       	cmpb   $0x0,0xc(%rsp)
     569:	48 8b 74 24 60       	mov    0x60(%rsp),%rsi
     56e:	4c 8b 44 24 28       	mov    0x28(%rsp),%r8
     573:	4c 8b 4c 24 18       	mov    0x18(%rsp),%r9
     578:	48 8b 54 24 58       	mov    0x58(%rsp),%rdx
     57d:	4c 8b 74 24 40       	mov    0x40(%rsp),%r14
     582:	74 27                	je     0x5ab
     584:	49 ff 82 d0 00 00 00 	incq   0xd0(%r10)
     58b:	eb 1e                	jmp    0x5ab
     58d:	80 7c 24 0c 00       	cmpb   $0x0,0xc(%rsp)
     592:	74 07                	je     0x59b
     594:	49 ff 82 d0 00 00 00 	incq   0xd0(%r10)
     59b:	f6 44 24 50 01       	testb  $0x1,0x50(%rsp)
     5a0:	48 8b 54 24 58       	mov    0x58(%rsp),%rdx
     5a5:	0f 84 f8 fb ff ff    	je     0x1a3
     5ab:	4d 89 d4             	mov    %r10,%r12
     5ae:	4d 89 cf             	mov    %r9,%r15
     5b1:	4c 89 c7             	mov    %r8,%rdi
     5b4:	48 81 c4 88 00 00 00 	add    $0x88,%rsp
     5bb:	e9 a4 05 00 00       	jmp    0xb64
     5c0:	41 8b 04 24          	mov    (%r12),%eax
     5c4:	85 c0                	test   %eax,%eax
     5c6:	0f 88 df fc ff ff    	js     0x2ab
     5cc:	ff c8                	dec    %eax
     5ce:	41 89 04 24          	mov    %eax,(%r12)
     5d2:	0f 85 d3 fc ff ff    	jne    0x2ab
     5d8:	4c 89 e7             	mov    %r12,%rdi
     5db:	ff 15 d4 07 00 00    	call   *0x7d4(%rip)        # 0xdb5
     5e1:	e9 c5 fc ff ff       	jmp    0x2ab
     5e6:	49 ff 82 d8 00 00 00 	incq   0xd8(%r10)
     5ed:	80 7c 24 0c 00       	cmpb   $0x0,0xc(%rsp)
     5f2:	48 8b 74 24 60       	mov    0x60(%rsp),%rsi
     5f7:	4c 8b 44 24 28       	mov    0x28(%rsp),%r8
     5fc:	4c 8b 4c 24 18       	mov    0x18(%rsp),%r9
     601:	4c 8b 74 24 40       	mov    0x40(%rsp),%r14
     606:	0f 84 97 fb ff ff    	je     0x1a3
     60c:	49 ff 82 d0 00 00 00 	incq   0xd0(%r10)
     613:	e9 8b fb ff ff       	jmp    0x1a3
     618:	48 83 ec 18          	sub    $0x18,%rsp
     61c:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
     621:	48 89 74 24 08       	mov    %rsi,0x8(%rsp)
     626:	48 89 fb             	mov    %rdi,%rbx
     629:	48 89 f8             	mov    %rdi,%rax
     62c:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     630:	48 8b 78 10          	mov    0x10(%rax),%rdi
     634:	48 8b 48 18          	mov    0x18(%rax),%rcx
     638:	48 01 f9             	add    %rdi,%rcx
     63b:	48 89 48 10          	mov    %rcx,0x10(%rax)
     63f:	48 ff 48 20          	decq   0x20(%rax)
     643:	ff 15 94 07 00 00    	call   *0x794(%rip)        # 0xddd
     649:	48 85 c0             	test   %rax,%rax
     64c:	74 18                	je     0x666
     64e:	0f b7 50 06          	movzwl 0x6(%rax),%edx
     652:	83 e2 01             	and    $0x1,%edx
     655:	48 09 c2             	or     %rax,%rdx
     658:	48 89 df             	mov    %rbx,%rdi
     65b:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     660:	48 83 c4 18          	add    $0x18,%rsp
     664:	eb 21                	jmp    0x687
     666:	49 89 1e             	mov    %rbx,(%r14)
     669:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     66e:	49 89 76 08          	mov    %rsi,0x8(%r14)
     672:	49 83 c6 10          	add    $0x10,%r14
     676:	48 89 df             	mov    %rbx,%rdi
     679:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
     67e:	48 83 c4 18          	add    $0x18,%rsp
     682:	e9 61 05 00 00       	jmp    0xbe8
     687:	48 b8 2c f4 db 16 22 	movabs $0x7f2216dbf42c,%rax
     68e:	7f 00 00
     691:	49 89 45 38          	mov    %rax,0x38(%r13)
     695:	49 8b 45 78          	mov    0x78(%r13),%rax
     699:	49 89 55 78          	mov    %rdx,0x78(%r13)
     69d:	48 89 c2             	mov    %rax,%rdx
     6a0:	49 89 3e             	mov    %rdi,(%r14)
     6a3:	49 89 76 08          	mov    %rsi,0x8(%r14)
     6a7:	49 83 c6 10          	add    $0x10,%r14
     6ab:	48 89 d7             	mov    %rdx,%rdi
     6ae:	4d 89 75 40          	mov    %r14,0x40(%r13)
     6b2:	40 f6 c7 01          	test   $0x1,%dil
     6b6:	75 0f                	jne    0x6c7
     6b8:	ff 0f                	decl   (%rdi)
     6ba:	75 0b                	jne    0x6c7
     6bc:	50                   	push   %rax
     6bd:	ff 15 f2 06 00 00    	call   *0x6f2(%rip)        # 0xdb5
     6c3:	48 83 c4 08          	add    $0x8,%rsp
     6c7:	31 ff                	xor    %edi,%edi
     6c9:	31 f6                	xor    %esi,%esi
     6cb:	31 d2                	xor    %edx,%edx
     6cd:	41 80 7c 24 22 00    	cmpb   $0x0,0x22(%r12)
     6d3:	0f 84 43 05 00 00    	je     0xc1c
     6d9:	49 8b 7d 70          	mov    0x70(%r13),%rdi
     6dd:	48 83 cf 01          	or     $0x1,%rdi
     6e1:	49 8b 75 60          	mov    0x60(%r13),%rsi
     6e5:	48 83 ce 01          	or     $0x1,%rsi
     6e9:	49 8b 55 78          	mov    0x78(%r13),%rdx
     6ed:	48 83 ca 01          	or     $0x1,%rdx
     6f1:	48 89 d0             	mov    %rdx,%rax
     6f4:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     6f8:	48 83 78 10 10       	cmpq   $0x10,0x10(%rax)
     6fd:	0f 83 5c 05 00 00    	jae    0xc5f
     703:	48 89 f0             	mov    %rsi,%rax
     706:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     70a:	48 b9 00 bc 31 0e 8c 	movabs $0x558c0e31bc00,%rcx
     711:	55 00 00
     714:	48 39 48 08          	cmp    %rcx,0x8(%rax)
     718:	0f 85 41 05 00 00    	jne    0xc5f
     71e:	48 83 78 10 10       	cmpq   $0x10,0x10(%rax)
     723:	0f 83 36 05 00 00    	jae    0xc5f
     729:	49 89 3e             	mov    %rdi,(%r14)
     72c:	49 83 c6 08          	add    $0x8,%r14
     730:	48 89 f7             	mov    %rsi,%rdi
     733:	48 89 d6             	mov    %rdx,%rsi
     736:	48 83 ec 18          	sub    $0x18,%rsp
     73a:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
     73f:	48 89 fb             	mov    %rdi,%rbx
     742:	48 83 e7 fe          	and    $0xfffffffffffffffe,%rdi
     746:	48 89 74 24 08       	mov    %rsi,0x8(%rsp)
     74b:	48 83 e6 fe          	and    $0xfffffffffffffffe,%rsi
     74f:	ff 15 70 06 00 00    	call   *0x670(%rip)        # 0xdc5
     755:	48 83 f8 01          	cmp    $0x1,%rax
     759:	75 16                	jne    0x771
     75b:	48 89 df             	mov    %rbx,%rdi
     75e:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     763:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
     768:	48 83 c4 18          	add    $0x18,%rsp
     76c:	e9 22 05 00 00       	jmp    0xc93
     771:	48 89 c7             	mov    %rax,%rdi
     774:	48 89 de             	mov    %rbx,%rsi
     777:	48 8b 54 24 08       	mov    0x8(%rsp),%rdx
     77c:	48 83 c4 18          	add    $0x18,%rsp
     780:	49 8b 75 68          	mov    0x68(%r13),%rsi
     784:	48 83 ce 01          	or     $0x1,%rsi
     788:	48 89 f0             	mov    %rsi,%rax
     78b:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     78f:	48 b9 00 bc 31 0e 8c 	movabs $0x558c0e31bc00,%rcx
     796:	55 00 00
     799:	48 39 48 08          	cmp    %rcx,0x8(%rax)
     79d:	0f 85 20 05 00 00    	jne    0xcc3
     7a3:	48 83 78 10 10       	cmpq   $0x10,0x10(%rax)
     7a8:	0f 83 15 05 00 00    	jae    0xcc3
     7ae:	48 83 ec 18          	sub    $0x18,%rsp
     7b2:	48 89 54 24 08       	mov    %rdx,0x8(%rsp)
     7b7:	49 89 f1             	mov    %rsi,%r9
     7ba:	48 89 fb             	mov    %rdi,%rbx
     7bd:	48 83 e7 fe          	and    $0xfffffffffffffffe,%rdi
     7c1:	83 3f 00             	cmpl   $0x0,(%rdi)
     7c4:	0f 88 92 00 00 00    	js     0x85c
     7ca:	48 8b 47 10          	mov    0x10(%rdi),%rax
     7ce:	83 e0 03             	and    $0x3,%eax
     7d1:	b9 01 00 00 00       	mov    $0x1,%ecx
     7d6:	ba 01 00 00 00       	mov    $0x1,%edx
     7db:	48 29 c2             	sub    %rax,%rdx
     7de:	44 8b 47 18          	mov    0x18(%rdi),%r8d
     7e2:	4c 0f af c2          	imul   %rdx,%r8
     7e6:	4c 89 ce             	mov    %r9,%rsi
     7e9:	48 83 e6 fe          	and    $0xfffffffffffffffe,%rsi
     7ed:	48 8b 46 10          	mov    0x10(%rsi),%rax
     7f1:	83 e0 03             	and    $0x3,%eax
     7f4:	48 29 c1             	sub    %rax,%rcx
     7f7:	8b 46 18             	mov    0x18(%rsi),%eax
     7fa:	48 0f af c1          	imul   %rcx,%rax
     7fe:	4c 01 c0             	add    %r8,%rax
     801:	48 8d 88 ff fb ff ff 	lea    -0x401(%rax),%rcx
     808:	48 81 f9 fa fb ff ff 	cmp    $0xfffffffffffffbfa,%rcx
     80f:	0f 92 c1             	setb   %cl
     812:	48 8d 90 ff ff ff 3f 	lea    0x3fffffff(%rax),%rdx
     819:	48 81 fa ff ff ff 7f 	cmp    $0x7fffffff,%rdx
     820:	0f 92 c2             	setb   %dl
     823:	20 ca                	and    %cl,%dl
     825:	80 fa 01             	cmp    $0x1,%dl
     828:	75 39                	jne    0x863
     82a:	48 89 c1             	mov    %rax,%rcx
     82d:	48 c1 e9 3f          	shr    $0x3f,%rcx
     831:	48 8d 0c 4d 08 00 00 	lea    0x8(,%rcx,2),%rcx
     838:	00
     839:	48 89 4f 10          	mov    %rcx,0x10(%rdi)
     83d:	48 89 c1             	mov    %rax,%rcx
     840:	48 f7 d9             	neg    %rcx
     843:	48 0f 48 c8          	cmovs  %rax,%rcx
     847:	89 4f 18             	mov    %ecx,0x18(%rdi)
     84a:	f6 c3 01             	test   $0x1,%bl
     84d:	75 02                	jne    0x851
     84f:	ff 03                	incl   (%rbx)
     851:	48 89 d8             	mov    %rbx,%rax
     854:	48 83 fb 01          	cmp    $0x1,%rbx
     858:	74 09                	je     0x863
     85a:	eb 49                	jmp    0x8a5
     85c:	4c 89 ce             	mov    %r9,%rsi
     85f:	48 83 e6 fe          	and    $0xfffffffffffffffe,%rsi
     863:	4c 89 64 24 10       	mov    %r12,0x10(%rsp)
     868:	4d 89 ec             	mov    %r13,%r12
     86b:	4d 89 f5             	mov    %r14,%r13
     86e:	4d 89 fe             	mov    %r15,%r14
     871:	4d 89 cf             	mov    %r9,%r15
     874:	ff 15 43 05 00 00    	call   *0x543(%rip)        # 0xdbd
     87a:	4d 89 f9             	mov    %r15,%r9
     87d:	4d 89 f7             	mov    %r14,%r15
     880:	4d 89 ee             	mov    %r13,%r14
     883:	4d 89 e5             	mov    %r12,%r13
     886:	4c 8b 64 24 10       	mov    0x10(%rsp),%r12
     88b:	48 83 f8 01          	cmp    $0x1,%rax
     88f:	75 14                	jne    0x8a5
     891:	48 89 df             	mov    %rbx,%rdi
     894:	4c 89 ce             	mov    %r9,%rsi
     897:	48 8b 54 24 08       	mov    0x8(%rsp),%rdx
     89c:	48 83 c4 18          	add    $0x18,%rsp
     8a0:	e9 1e 04 00 00       	jmp    0xcc3
     8a5:	48 89 c7             	mov    %rax,%rdi
     8a8:	48 89 de             	mov    %rbx,%rsi
     8ab:	4c 89 ca             	mov    %r9,%rdx
     8ae:	48 83 c4 18          	add    $0x18,%rsp
     8b2:	48 89 f3             	mov    %rsi,%rbx
     8b5:	f6 c3 01             	test   $0x1,%bl
     8b8:	75 52                	jne    0x90c
     8ba:	ff 0b                	decl   (%rbx)
     8bc:	75 4e                	jne    0x90c
     8be:	48 83 ec 18          	sub    $0x18,%rsp
     8c2:	48 89 7c 24 08       	mov    %rdi,0x8(%rsp)
     8c7:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
     8cc:	48 b8 30 22 35 0e 8c 	movabs $0x558c0e352230,%rax
     8d3:	55 00 00
     8d6:	48 8b 00             	mov    (%rax),%rax
     8d9:	48 85 c0             	test   %rax,%rax
     8dc:	74 17                	je     0x8f5
     8de:	48 b9 38 22 35 0e 8c 	movabs $0x558c0e352238,%rcx
     8e5:	55 00 00
     8e8:	48 8b 11             	mov    (%rcx),%rdx
     8eb:	48 89 df             	mov    %rbx,%rdi
     8ee:	be 01 00 00 00       	mov    $0x1,%esi
     8f3:	ff d0                	call   *%rax
     8f5:	48 89 df             	mov    %rbx,%rdi
     8f8:	ff 15 e7 04 00 00    	call   *0x4e7(%rip)        # 0xde5
     8fe:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
     903:	48 8b 7c 24 08       	mov    0x8(%rsp),%rdi
     908:	48 83 c4 18          	add    $0x18,%rsp
     90c:	48 89 de             	mov    %rbx,%rsi
     90f:	48 b8 4c f4 db 16 22 	movabs $0x7f2216dbf44c,%rax
     916:	7f 00 00
     919:	49 89 45 38          	mov    %rax,0x38(%r13)
     91d:	48 89 fe             	mov    %rdi,%rsi
     920:	49 8b 7e f8          	mov    -0x8(%r14),%rdi
     924:	49 83 c6 f8          	add    $0xfffffffffffffff8,%r14
     928:	48 83 ec 18          	sub    $0x18,%rsp
     92c:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
     931:	48 89 f0             	mov    %rsi,%rax
     934:	48 89 fb             	mov    %rdi,%rbx
     937:	4c 89 3c 24          	mov    %r15,(%rsp)
     93b:	48 83 e7 fe          	and    $0xfffffffffffffffe,%rdi
     93f:	48 83 e6 fe          	and    $0xfffffffffffffffe,%rsi
     943:	49 89 1e             	mov    %rbx,(%r14)
     946:	48 89 44 24 08       	mov    %rax,0x8(%rsp)
     94b:	49 89 46 08          	mov    %rax,0x8(%r14)
     94f:	4d 8d 7e 10          	lea    0x10(%r14),%r15
     953:	4d 89 7d 40          	mov    %r15,0x40(%r13)
     957:	48 b8 0d 00 00 00 00 	movabs $0xd,%rax
     95e:	00 00 00
     961:	0f b7 c0             	movzwl %ax,%eax
     964:	48 b9 a0 95 2c 0e 8c 	movabs $0x558c0e2c95a0,%rcx
     96b:	55 00 00
     96e:	ff 14 c1             	call   *(%rcx,%rax,8)
     971:	48 85 c0             	test   %rax,%rax
     974:	74 1c                	je     0x992
     976:	0f b7 78 06          	movzwl 0x6(%rax),%edi
     97a:	83 e7 01             	and    $0x1,%edi
     97d:	48 09 c7             	or     %rax,%rdi
     980:	4c 8b 3c 24          	mov    (%rsp),%r15
     984:	48 89 de             	mov    %rbx,%rsi
     987:	48 8b 54 24 08       	mov    0x8(%rsp),%rdx
     98c:	48 83 c4 18          	add    $0x18,%rsp
     990:	eb 1d                	jmp    0x9af
     992:	4d 89 fe             	mov    %r15,%r14
     995:	4c 8b 3c 24          	mov    (%rsp),%r15
     999:	48 89 df             	mov    %rbx,%rdi
     99c:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     9a1:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
     9a6:	48 83 c4 18          	add    $0x18,%rsp
     9aa:	e9 44 03 00 00       	jmp    0xcf3
     9af:	48 89 d3             	mov    %rdx,%rbx
     9b2:	f6 c3 01             	test   $0x1,%bl
     9b5:	75 52                	jne    0xa09
     9b7:	ff 0b                	decl   (%rbx)
     9b9:	75 4e                	jne    0xa09
     9bb:	48 83 ec 18          	sub    $0x18,%rsp
     9bf:	48 89 7c 24 08       	mov    %rdi,0x8(%rsp)
     9c4:	48 89 74 24 10       	mov    %rsi,0x10(%rsp)
     9c9:	48 b8 30 22 35 0e 8c 	movabs $0x558c0e352230,%rax
     9d0:	55 00 00
     9d3:	48 8b 00             	mov    (%rax),%rax
     9d6:	48 85 c0             	test   %rax,%rax
     9d9:	74 17                	je     0x9f2
     9db:	48 b9 38 22 35 0e 8c 	movabs $0x558c0e352238,%rcx
     9e2:	55 00 00
     9e5:	48 8b 11             	mov    (%rcx),%rdx
     9e8:	48 89 df             	mov    %rbx,%rdi
     9eb:	be 01 00 00 00       	mov    $0x1,%esi
     9f0:	ff d0                	call   *%rax
     9f2:	48 89 df             	mov    %rbx,%rdi
     9f5:	ff 15 ea 03 00 00    	call   *0x3ea(%rip)        # 0xde5
     9fb:	48 8b 74 24 10       	mov    0x10(%rsp),%rsi
     a00:	48 8b 7c 24 08       	mov    0x8(%rsp),%rdi
     a05:	48 83 c4 18          	add    $0x18,%rsp
     a09:	48 89 da             	mov    %rbx,%rdx
     a0c:	41 80 7c 24 22 00    	cmpb   $0x0,0x22(%r12)
     a12:	0f 84 0f 03 00 00    	je     0xd27
     a18:	48 b8 58 f4 db 16 22 	movabs $0x7f2216dbf458,%rax
     a1f:	7f 00 00
     a22:	49 89 45 38          	mov    %rax,0x38(%r13)
     a26:	49 8b 45 70          	mov    0x70(%r13),%rax
     a2a:	49 89 7d 70          	mov    %rdi,0x70(%r13)
     a2e:	48 89 c7             	mov    %rax,%rdi
     a31:	4d 89 75 40          	mov    %r14,0x40(%r13)
     a35:	40 f6 c7 01          	test   $0x1,%dil
     a39:	75 0f                	jne    0xa4a
     a3b:	ff 0f                	decl   (%rdi)
     a3d:	75 0b                	jne    0xa4a
     a3f:	50                   	push   %rax
     a40:	ff 15 6f 03 00 00    	call   *0x36f(%rip)        # 0xdb5
     a46:	48 83 c4 08          	add    $0x8,%rsp
     a4a:	31 ff                	xor    %edi,%edi
     a4c:	31 f6                	xor    %esi,%esi
     a4e:	31 d2                	xor    %edx,%edx
     a50:	e9 f7 f5 ff ff       	jmp    0x4c
     a55:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     a5c:	00 00 00 00
     a60:	4d 89 75 40          	mov    %r14,0x40(%r13)
     a64:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     a69:	75 0e                	jne    0xa79
     a6b:	48 b8 c0 e9 32 0e 8c 	movabs $0x558c0e32e9c0,%rax
     a72:	55 00 00
     a75:	48 8b 00             	mov    (%rax),%rax
     a78:	c3                   	ret
     a79:	49 8b 45 00          	mov    0x0(%r13),%rax
     a7d:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     a81:	48 b9 29 00 00 00 00 	movabs $0x29,%rcx
     a88:	00 00 00
     a8b:	89 c9                	mov    %ecx,%ecx
     a8d:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     a91:	48 05 c8 00 00 00    	add    $0xc8,%rax
     a97:	c3                   	ret
     a98:	49 8b 45 00          	mov    0x0(%r13),%rax
     a9c:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     aa0:	48 b9 29 00 00 00 00 	movabs $0x29,%rcx
     aa7:	00 00 00
     aaa:	89 c9                	mov    %ecx,%ecx
     aac:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     ab0:	48 05 c8 00 00 00    	add    $0xc8,%rax
     ab6:	49 89 45 38          	mov    %rax,0x38(%r13)
     aba:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     ac1:	00 00 00 00
     ac5:	4d 89 75 40          	mov    %r14,0x40(%r13)
     ac9:	31 c0                	xor    %eax,%eax
     acb:	c3                   	ret
     acc:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     ad3:	00 00 00 00
     ad7:	4d 89 75 40          	mov    %r14,0x40(%r13)
     adb:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     ae0:	75 0e                	jne    0xaf0
     ae2:	48 b8 c0 e9 32 0e 8c 	movabs $0x558c0e32e9c0,%rax
     ae9:	55 00 00
     aec:	48 8b 00             	mov    (%rax),%rax
     aef:	c3                   	ret
     af0:	49 8b 45 00          	mov    0x0(%r13),%rax
     af4:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     af8:	48 b9 10 00 00 00 00 	movabs $0x10,%rcx
     aff:	00 00 00
     b02:	89 c9                	mov    %ecx,%ecx
     b04:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     b08:	48 05 c8 00 00 00    	add    $0xc8,%rax
     b0e:	c3                   	ret
     b0f:	48 b8 38 82 0c 36 8c 	movabs $0x558c360c8238,%rax
     b16:	55 00 00
     b19:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     b20:	48 b8 40 82 0c 36 8c 	movabs $0x558c360c8240,%rax
     b27:	55 00 00
     b2a:	4c 8b 20             	mov    (%rax),%r12
     b2d:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     b32:	ff e0                	jmp    *%rax
     b34:	48 b8 48 82 0c 36 8c 	movabs $0x558c360c8248,%rax
     b3b:	55 00 00
     b3e:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     b45:	49 89 3e             	mov    %rdi,(%r14)
     b48:	49 89 76 08          	mov    %rsi,0x8(%r14)
     b4c:	49 83 c6 10          	add    $0x10,%r14
     b50:	48 b8 50 82 0c 36 8c 	movabs $0x558c360c8250,%rax
     b57:	55 00 00
     b5a:	4c 8b 20             	mov    (%rax),%r12
     b5d:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     b62:	ff e0                	jmp    *%rax
     b64:	50                   	push   %rax
     b65:	49 89 3e             	mov    %rdi,(%r14)
     b68:	49 89 76 08          	mov    %rsi,0x8(%r14)
     b6c:	49 83 c6 10          	add    $0x10,%r14
     b70:	4d 89 75 40          	mov    %r14,0x40(%r13)
     b74:	4c 89 ff             	mov    %r15,%rdi
     b77:	ff 15 50 02 00 00    	call   *0x250(%rip)        # 0xdcd
     b7d:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     b84:	00 00 00 00
     b88:	4d 89 75 40          	mov    %r14,0x40(%r13)
     b8c:	85 c0                	test   %eax,%eax
     b8e:	74 04                	je     0xb94
     b90:	31 c0                	xor    %eax,%eax
     b92:	eb 1e                	jmp    0xbb2
     b94:	49 8b 45 00          	mov    0x0(%r13),%rax
     b98:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     b9c:	48 b9 29 00 00 00 00 	movabs $0x29,%rcx
     ba3:	00 00 00
     ba6:	89 c9                	mov    %ecx,%ecx
     ba8:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     bac:	48 05 c8 00 00 00    	add    $0xc8,%rax
     bb2:	59                   	pop    %rcx
     bb3:	c3                   	ret
     bb4:	49 8b 45 00          	mov    0x0(%r13),%rax
     bb8:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     bbc:	48 b9 22 00 00 00 00 	movabs $0x22,%rcx
     bc3:	00 00 00
     bc6:	89 c9                	mov    %ecx,%ecx
     bc8:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     bcc:	48 05 c8 00 00 00    	add    $0xc8,%rax
     bd2:	49 89 45 38          	mov    %rax,0x38(%r13)
     bd6:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     bdd:	00 00 00 00
     be1:	4d 89 75 40          	mov    %r14,0x40(%r13)
     be5:	31 c0                	xor    %eax,%eax
     be7:	c3                   	ret
     be8:	49 8b 45 00          	mov    0x0(%r13),%rax
     bec:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     bf0:	48 b9 10 00 00 00 00 	movabs $0x10,%rcx
     bf7:	00 00 00
     bfa:	89 c9                	mov    %ecx,%ecx
     bfc:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     c00:	48 05 c8 00 00 00    	add    $0xc8,%rax
     c06:	49 89 45 38          	mov    %rax,0x38(%r13)
     c0a:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     c11:	00 00 00 00
     c15:	4d 89 75 40          	mov    %r14,0x40(%r13)
     c19:	31 c0                	xor    %eax,%eax
     c1b:	c3                   	ret
     c1c:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     c23:	00 00 00 00
     c27:	4d 89 75 40          	mov    %r14,0x40(%r13)
     c2b:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     c30:	75 0e                	jne    0xc40
     c32:	48 b8 c0 e9 32 0e 8c 	movabs $0x558c0e32e9c0,%rax
     c39:	55 00 00
     c3c:	48 8b 00             	mov    (%rax),%rax
     c3f:	c3                   	ret
     c40:	49 8b 45 00          	mov    0x0(%r13),%rax
     c44:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     c48:	48 b9 13 00 00 00 00 	movabs $0x13,%rcx
     c4f:	00 00 00
     c52:	89 c9                	mov    %ecx,%ecx
     c54:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     c58:	48 05 c8 00 00 00    	add    $0xc8,%rax
     c5e:	c3                   	ret
     c5f:	48 b8 58 82 0c 36 8c 	movabs $0x558c360c8258,%rax
     c66:	55 00 00
     c69:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     c70:	49 89 3e             	mov    %rdi,(%r14)
     c73:	49 89 76 08          	mov    %rsi,0x8(%r14)
     c77:	49 89 56 10          	mov    %rdx,0x10(%r14)
     c7b:	49 83 c6 18          	add    $0x18,%r14
     c7f:	48 b8 60 82 0c 36 8c 	movabs $0x558c360c8260,%rax
     c86:	55 00 00
     c89:	4c 8b 20             	mov    (%rax),%r12
     c8c:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     c91:	ff e0                	jmp    *%rax
     c93:	48 b8 68 82 0c 36 8c 	movabs $0x558c360c8268,%rax
     c9a:	55 00 00
     c9d:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     ca4:	49 89 3e             	mov    %rdi,(%r14)
     ca7:	49 89 76 08          	mov    %rsi,0x8(%r14)
     cab:	49 83 c6 10          	add    $0x10,%r14
     caf:	48 b8 70 82 0c 36 8c 	movabs $0x558c360c8270,%rax
     cb6:	55 00 00
     cb9:	4c 8b 20             	mov    (%rax),%r12
     cbc:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     cc1:	ff e0                	jmp    *%rax
     cc3:	48 b8 78 82 0c 36 8c 	movabs $0x558c360c8278,%rax
     cca:	55 00 00
     ccd:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     cd4:	49 89 3e             	mov    %rdi,(%r14)
     cd7:	49 89 76 08          	mov    %rsi,0x8(%r14)
     cdb:	49 83 c6 10          	add    $0x10,%r14
     cdf:	48 b8 80 82 0c 36 8c 	movabs $0x558c360c8280,%rax
     ce6:	55 00 00
     ce9:	4c 8b 20             	mov    (%rax),%r12
     cec:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     cf1:	ff e0                	jmp    *%rax
     cf3:	49 8b 45 00          	mov    0x0(%r13),%rax
     cf7:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     cfb:	48 b9 22 00 00 00 00 	movabs $0x22,%rcx
     d02:	00 00 00
     d05:	89 c9                	mov    %ecx,%ecx
     d07:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     d0b:	48 05 c8 00 00 00    	add    $0xc8,%rax
     d11:	49 89 45 38          	mov    %rax,0x38(%r13)
     d15:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     d1c:	00 00 00 00
     d20:	4d 89 75 40          	mov    %r14,0x40(%r13)
     d24:	31 c0                	xor    %eax,%eax
     d26:	c3                   	ret
     d27:	49 89 3e             	mov    %rdi,(%r14)
     d2a:	49 83 c6 08          	add    $0x8,%r14
     d2e:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     d35:	00 00 00 00
     d39:	4d 89 75 40          	mov    %r14,0x40(%r13)
     d3d:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     d42:	75 0e                	jne    0xd52
     d44:	48 b8 c0 e9 32 0e 8c 	movabs $0x558c0e32e9c0,%rax
     d4b:	55 00 00
     d4e:	48 8b 00             	mov    (%rax),%rax
     d51:	c3                   	ret
     d52:	49 8b 45 00          	mov    0x0(%r13),%rax
     d56:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     d5a:	48 b9 28 00 00 00 00 	movabs $0x28,%rcx
     d61:	00 00 00
     d64:	89 c9                	mov    %ecx,%ecx
     d66:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     d6a:	48 05 c8 00 00 00    	add    $0xc8,%rax
     d70:	c3                   	ret
     d71:	50                   	push   %rax
     d72:	48 bf 8d cd 7b 16 22 	movabs $0x7f22167bcd8d,%rdi
     d79:	7f 00 00
     d7c:	48 be 98 cd 7b 16 22 	movabs $0x7f22167bcd98,%rsi
     d83:	7f 00 00
     d86:	ff 15 49 00 00 00    	call   *0x49(%rip)        # 0xdd5
     d8c:	00 5f 4a             	add    %bl,0x4a(%rdi)
     d8f:	49 54                	rex.WB push %r12
     d91:	5f                   	pop    %rdi
     d92:	45                   	rex.RB
     d93:	4e 54                	rex.WRX push %rsp
     d95:	52                   	push   %rdx
     d96:	59                   	pop    %rcx
     d97:	00 46 61             	add    %al,0x61(%rsi)
     d9a:	74 61                	je     0xdfd
     d9c:	6c                   	insb   (%dx),%es:(%rdi)
     d9d:	20 65 72             	and    %ah,0x72(%rbp)
     da0:	72 6f                	jb     0xe11
     da2:	72 20                	jb     0xdc4
     da4:	75 6f                	jne    0xe15
     da6:	70 20                	jo     0xdc8
     da8:	65 78 65             	gs js  0xe10
     dab:	63 75 74             	movsxd 0x74(%rbp),%esi
     dae:	65 64 2e 00 00       	gs fs add %al,%fs:(%rax)
     db3:	00 00                	add    %al,(%rax)
     db5:	e0 60                	loopne 0xe17
     db7:	e4 0d                	in     $0xd,%al
     db9:	8c 55 00             	mov    %ss,0x0(%rbp)
     dbc:	00 80 fa e1 0d 8c    	add    %al,-0x73f21e06(%rax)
     dc2:	55                   	push   %rbp
     dc3:	00 00                	add    %al,(%rax)
     dc5:	00 fd                	add    %bh,%ch
     dc7:	e1 0d                	loope  0xdd6
     dc9:	8c 55 00             	mov    %ss,0x0(%rbp)
     dcc:	00 e0                	add    %ah,%al
     dce:	4b f9                	rex.WXB stc
     dd0:	0d 8c 55 00 00       	or     $0x558c,%eax
     dd5:	50                   	push   %rax
     dd6:	30 01                	xor    %al,(%rcx)
     dd8:	0e                   	(bad)
     dd9:	8c 55 00             	mov    %ss,0x0(%rbp)
     ddc:	00 d0                	add    %dl,%al
     dde:	6b e1 0d             	imul   $0xd,%ecx,%esp
     de1:	8c 55 00             	mov    %ss,0x0(%rbp)
     de4:	00 80 aa e0 0d 8c    	add    %al,-0x73f21f56(%rax)
     dea:	55                   	push   %rbp
     deb:	00 00                	add    %al,(%rax)
     ded:	f0 32 ff             	lock xor %bh,%bh
     df0:	0d 8c 55 00 00       	or     $0x558c,%eax
     df5:	60                   	(bad)
     df6:	cb                   	lret
     df7:	e1 0d                	loope  0xe06
     df9:	8c 55 00             	mov    %ss,0x0(%rbp)
     dfc:	00 50 e1             	add    %dl,-0x1f(%rax)
     dff:	d5 0d 8c 55 00       	{rex2 0xd} mov %ss,0x0(%r13)
     e04:	00 f0                	add    %dh,%al
     e06:	c5 e1 0d             	(bad)
     e09:	8c 55 00             	mov    %ss,0x0(%rbp)
	...
