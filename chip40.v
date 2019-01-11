
module chip (
	output	LED_R,
	output	LED_G,
	output	LED_B
	);

	wire clk, led;

	SB_HFOSC u_hfosc (
        	.CLKHFPU(1'b1),
        	.CLKHFEN(1'b1),
        	.CLKHF(clk)
    	);

	test_deflate_bench mytest (
    		clk,
    		o_led,
    		led0_g,
    		led1_b,
    		led2_r
     );

	//blink my_blink (
	//	.clk(clk),
	//	.rst(0),
    	//	.led(led)
	//);

	assign LED_R = led2_r;
	assign LED_G = led0_g;
	assign LED_B = led1_b;

endmodule
