package com.ziokt.effort;
import android.app.Instrumentation;
import android.os.Bundle;
import android.os.Build;

/** Runs inside the actual 32/64-bit Android runtime, not a host JVM mock. */
public final class Smoke extends Instrumentation {
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){
        Bundle result=new Bundle();
        try {
            if(!Work.hash("abc").equals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"))throw new AssertionError("native SHA-256 vector");
            if(!Work.ORIGIN.equals("https://fendou.ziokt.com"))throw new AssertionError("origin");
            Work task=new Work(s->{});task.cancel();try{task.check();throw new AssertionError("cancel failed");}catch(java.util.concurrent.CancellationException expected){}
            if(Build.VERSION.SDK_INT<28)throw new AssertionError("minimum API");
            result.putString("native_checks","passed");result.putInt("checks",4);result.putBoolean("is_64_bit",android.os.Process.is64Bit());result.putLong("max_heap",Runtime.getRuntime().maxMemory());finish(-1,result);
        } catch(Throwable e){result.putString("native_checks","failed: "+e.getClass().getName());finish(1,result);}
    }
}
