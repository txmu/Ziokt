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
            String identity=Work.newWorkerId();if(!identity.matches("[a-f0-9]{48}")||identity.equals(Work.newWorkerId()))throw new AssertionError("independent worker identity");
            final boolean[] active={true};
            Work coordinated=new Work(value->{}){
                @Override org.json.JSONObject post(String path,org.json.JSONObject value,String token) throws Exception {
                    long expires=System.currentTimeMillis()/1000+120;
                    if(path.equals("/api/job/status"))return object("active",active[0],"expires",expires);
                    if(path.equals("/api/gimps/heartbeat"))return object("renewed",active[0],"expires",expires);
                    throw new AssertionError("unexpected endpoint");
                }
            };
            org.json.JSONObject job=Work.object("token","aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","expires",System.currentTimeMillis()/1000+60);
            coordinated.beginLease(job,false);active[0]=false;
            try{coordinated.guardLease(true);throw new AssertionError("completed task kept computing");}catch(java.io.IOException expected){}
            active[0]=true;coordinated.beginLease(job,true);long before=coordinated.leaseExpires;coordinated.guardLease(true);if(coordinated.leaseExpires<before)throw new AssertionError("lease did not renew");
            org.json.JSONArray proofs=new org.json.JSONArray();
            for(int exponent:new int[]{7,11,127})proofs.put(GimpsProof.compute(exponent,true,null,(iteration,state)->{}));
            org.json.JSONObject resumed=GimpsProof.compute(7,true,Work.object("iteration",1,"s","9"),(iteration,state)->{});
            if(!resumed.getString("residue").equals(proofs.getJSONObject(0).getString("residue")))throw new AssertionError("checkpoint restart");
            try{GimpsProof.compute(127,true,null,(iteration,state)->{if(iteration==10)throw new java.util.concurrent.CancellationException();});throw new AssertionError("PRP cancel failed");}catch(java.util.concurrent.CancellationException expected){}
            result.putString("gimps_proofs",proofs.toString());
            result.putString("native_checks","passed");result.putInt("checks",10);result.putBoolean("is_64_bit",android.os.Process.is64Bit());result.putLong("max_heap",Runtime.getRuntime().maxMemory());finish(-1,result);
        } catch(Throwable e){result.putString("native_checks","failed: "+e.getClass().getName());finish(1,result);}
    }
}
