package com.ziokt.effort;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.concurrent.CancellationException;
import java.util.function.Consumer;
import javax.net.ssl.HttpsURLConnection;
import org.json.*;

/** One bounded native worker. No browser engine, JNI, connectivity probes or arbitrary destinations. */
final class Work {
    static final String ORIGIN="https://fendou.ziokt.com";
    volatile boolean cancelled;
    private volatile HttpsURLConnection request;
    private final Consumer<String> status;
    Work(Consumer<String> status) { this.status=status; }
    void cancel() { cancelled=true; HttpsURLConnection c=request;if(c!=null)c.disconnect(); }
    void check() { if(cancelled||Thread.currentThread().isInterrupted())throw new CancellationException(); }
    void pause(long ms) throws InterruptedException { check();Thread.sleep(ms);check(); }
    JSONObject post(String path,JSONObject value,String token) throws Exception {
        check();if(!path.matches("/api/(job|proof|people/direct/(open|[ab]/(read|write|ack|close)))"))throw new IOException("INVALID_ENDPOINT");
        byte[] body=value.toString().getBytes(StandardCharsets.UTF_8);if(body.length>8192)throw new IOException("REQUEST_LIMIT");
        HttpsURLConnection c=(HttpsURLConnection)new URL(ORIGIN+path).openConnection();request=c;
        c.setInstanceFollowRedirects(false);c.setConnectTimeout(15000);c.setReadTimeout(15000);c.setUseCaches(false);c.setRequestMethod("POST");c.setDoOutput(true);c.setFixedLengthStreamingMode(body.length);
        c.setRequestProperty("Content-Type","application/json");c.setRequestProperty("Origin",ORIGIN);
        if(token!=null)c.setRequestProperty("Authorization","Bearer "+token);
        try {
            check();try(OutputStream out=c.getOutputStream()){out.write(body);}
            int code=c.getResponseCode();InputStream input=code==200?c.getInputStream():c.getErrorStream();
            if(input==null)throw new IOException("HTTP_"+code);
            ByteArrayOutputStream bytes=new ByteArrayOutputStream(8192);byte[] buffer=new byte[2048];int count;
            try(InputStream in=input){while((count=in.read(buffer))!=-1){check();if(bytes.size()+count>32768)throw new IOException("RESPONSE_LIMIT");bytes.write(buffer,0,count);}}
            JSONObject result=new JSONObject(new String(bytes.toByteArray(),StandardCharsets.UTF_8));
            if(code!=200||result.has("error"))throw new IOException("HTTP_"+code);
            return result;
        } finally { c.disconnect();if(request==c)request=null; }
    }
    static JSONObject object(Object... values) throws JSONException {
        JSONObject result=new JSONObject();for(int i=0;i<values.length;i+=2)result.put((String)values[i],values[i+1]);return result;
    }
    static String hash(String value) throws Exception {
        byte[] bytes=MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));StringBuilder s=new StringBuilder(64);
        for(byte b:bytes)s.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return s.toString();
    }
    void compute(int level) throws Exception {
        JSONObject job=post("/api/job",object(),null);
        if(!job.getBoolean("available")){status.accept("等待真实计算任务，不进行无效计算");pause(5000);return;}
        String network=job.getString("network_id"),submitter=job.getString("submitter_id"),problem=job.getString("problem_id"),token=job.getString("token"),start=job.getString("start");
        long expires=job.getLong("expires"),limit=job.getLong("limit");
        if(!network.equals("ziokt-main")||!job.getString("engine_id").equals("corium/internal-engine-zero-v1")||job.getInt("difficulty")!=3||!submitter.matches("[a-f0-9]{64}")||!problem.matches("[a-f0-9]{64}")||!token.matches("[a-f0-9]{48}")||!start.matches("[0-9]{1,18}")||limit<1||limit>1000000||expires>System.currentTimeMillis()/1000+120)throw new IOException("INVALID_JOB");
        long base=Long.parseLong(start);if(base>Long.MAX_VALUE-limit)throw new IOException("NONCE_LIMIT");
        MessageDigest digest=MessageDigest.getInstance("SHA-256");int[] batches={8,16,32,64,128};int[] delays={100,80,60,40,20};int selected=Math.max(0,Math.min(4,level-1));
        status.accept("计算协作运行中 · 单线程 · 档位 "+(selected+1));
        for(long offset=0;offset<limit&&System.currentTimeMillis()/1000<expires;offset++) {
            check();String nonce=Long.toString(base+offset);byte[] raw=digest.digest((network+submitter+nonce+problem).getBytes(StandardCharsets.UTF_8));
            if(raw[0]==0&&(raw[1]&240)==0){JSONObject receipt=post("/api/proof",object("token",token,"nonce",nonce),null);if(!receipt.optBoolean("accepted",false))throw new IOException("PROOF_UNCONFIRMED");status.accept("证明已提交，等待原生共识；不保证奖励");pause(5000);return;}
            if(offset%batches[selected]==batches[selected]-1)pause(delays[selected]);
        }
    }
    JSONObject relay(String side,String op,JSONObject args,String token) throws Exception {
        JSONObject wire=object("arguments",args,"padding","");
        if(op.equals("write")){int n=6144-wire.toString().length();if(n>0){char[] padding=new char[n];java.util.Arrays.fill(padding,'0');wire.put("padding",new String(padding));}}
        return post("/api/people/direct/"+side+"/"+op,wire,token);
    }
    void network() throws Exception {
        JSONObject opened=post("/api/people/direct/open",object(),null);
        if(opened.getString("state").equals("waiting")){status.accept("主网直连已启用 · 等待真实转发任务（非匿名）");pause(5000);return;}
        String token=opened.getString("session");
        if(!opened.getString("state").equals("open")||!opened.getString("network_id").equals("ziokt-main")||!token.matches("[A-Za-z0-9_-]{40,64}"))throw new IOException("INVALID_SESSION");
        boolean[] fin={false,false};long total=0;String[] sides={"a","b"};
        while(!(fin[0]&&fin[1])) {
            check();boolean moved=false;
            for(int index=0;index<2;index++) {
                if(fin[index])continue;String from=sides[index],to=sides[1-index];JSONObject response=relay(from,"read",object("session",from),token);
                String state=response.getString("state");if(state.equals("idle"))continue;
                if(!state.equals("frame"))throw new IOException("INVALID_FRAME");JSONObject frame=response.getJSONObject("frame");String kind=frame.getString("kind"),encoded=frame.getString("data");long sequence=frame.getLong("sequence");
                if(sequence<0||sequence>=4294967296L||encoded.length()>5464||!(kind.equals("data")||kind.equals("fin")))throw new IOException("FRAME_LIMIT");
                byte[] bytes=android.util.Base64.decode(encoded,android.util.Base64.NO_WRAP);
                if(bytes.length>4096||!android.util.Base64.encodeToString(bytes,android.util.Base64.NO_WRAP).equals(encoded)||kind.equals("fin")!=(bytes.length==0))throw new IOException("INVALID_FRAME");
                JSONObject receipt=relay(to,"write",object("session",to,"frame",frame),token);if(!receipt.getString("state").equals("native_written"))throw new IOException("WRITE_UNCONFIRMED");
                if(!relay(from,"ack",object("session",from,"sequence",sequence),token).getString("state").equals("acknowledged"))throw new IOException("ACK_UNCONFIRMED");
                moved=true;if(kind.equals("fin"))fin[index]=true;else total+=bytes.length;
            }
            if(moved)status.accept("主网直连已转发 "+total+" 字节 · 非匿名，尚未结算贡献");pause(500);
        }
        relay("a","close",object("session","a"),token);
    }
}
