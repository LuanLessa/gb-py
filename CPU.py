class CPU:
    __slots__ = ['regs', 'PC', 'SP', 'BUS']

    def __init__(self, BUS):
        self.regs = bytearray(8) # 0:B, 1:C, 2:D, 3:E, 4:H, 5:L, 6:F, 7:A
        self.PC = 0x0000
        self.SP = 0x0000

        self.BUS = BUS()

    def run(self):
        regs = self.regs
        pc = self.PC
        sp = self.SP
        bus = self.BUS

        while True:
            opcode = bus.read(pc)
            # ticks += 4

            